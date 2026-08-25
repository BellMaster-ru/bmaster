from typing import Annotated, Any, Coroutine, Literal, Optional, Self, Type
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import AfterValidator, BaseModel, Field, ModelWrapValidatorHandler, SerializeAsAny, ValidationError, field_validator, model_validator

from passlib.context import CryptContext
import jwt
from sqlalchemy import select

from bmaster import configs, logs
from bmaster.api import api
from bmaster.api.auth.permissions import Role, RoleInfo
from bmaster.api.auth.users import User, UserInfo, Account, AccountInfo, UserLocalInfo
from bmaster.api.auth.service import RootUser, ServiceConfig, root


class JwtConfig(BaseModel):
	secret_key: str
	algorithm: str
	expire_minutes: int

class HasherConfig(BaseModel):
	schemas: str

class AuthConfig(BaseModel):
	jwt: JwtConfig
	hasher: HasherConfig
	service: ServiceConfig

config: Optional[AuthConfig] = None

logger = logs.main_logger.getChild('auth')

hasher: Optional[CryptContext] = None
oauth2_bearer = OAuth2PasswordBearer(tokenUrl='/api/auth/login_form')


def jwt_encode(data: Any) -> str:
	return jwt.encode(
		data,
		key=config.jwt.secret_key,
		algorithm=config.jwt.algorithm
	)

def jwt_decode(token: str):
	return jwt.decode(
		jwt=token,
		key=config.jwt.secret_key,
		algorithms=[config.jwt.algorithm]
	)


def require_bearer_jwt(token: Annotated[str, Depends(oauth2_bearer)]) -> Any:
	try:
		return jwt_decode(token)
	except jwt.InvalidTokenError:
		raise HTTPException(
			status.HTTP_401_UNAUTHORIZED, 'Could not validate credentials',
			headers={'WWW-Authenticate': 'Bearer'}
		)

class Token(BaseModel):
	access_token: str
	token_type: str

auth_token_registry: dict[str, Type[Self]] = dict()
class AuthToken(BaseModel):
	type: str

	def get_user(self) -> Coroutine[Any, Any, User]:
		raise NotImplementedError()
	
	@model_validator(mode='wrap')
	@classmethod
	def validate_type(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
		ent = handler(data)
		if cls is not AuthToken: return ent
		ent_type = ent.type
		ent_class = auth_token_registry.get(ent_type, None)
		if not ent_class: raise ValidationError(f'Unknown entity type: {ent_type}')
		return ent_class.model_validate(data)
	
	@staticmethod
	def register(cls: Type['AuthToken']) -> Type['AuthToken']:
		type_field = cls.model_fields.get('type', None)
		if not type_field: raise ValueError('Missing type field')
		auth_token_registry[type_field.default] = cls  # type: ignore
		return cls

@AuthToken.register
class UserToken(AuthToken):
	type: Literal['user'] = 'user'
	user_id: int

	async def get_user(self) -> Account:
		from bmaster.database import LocalSession
		async with LocalSession() as session:
			return await session.get(Account, self.user_id)

@AuthToken.register
class RootToken(AuthToken):
	type: Literal['root'] = 'root'

	async def get_user(self) -> RootUser:
		return root

def require_auth_token(jwt_data: Annotated[Any, Depends(require_bearer_jwt)]):
	try:
		token = AuthToken.model_validate(jwt_data)
		if (token.type == 'root') != config.service.enabled:
			raise HTTPException(
				status.HTTP_401_UNAUTHORIZED, 'bmaster.auth.service',
				headers={'WWW-Authenticate': 'Bearer'}
			)
	except ValidationError:
		raise HTTPException(
			status.HTTP_401_UNAUTHORIZED, 'bmaster.auth.invalid_token',
			headers={'WWW-Authenticate': 'Bearer'}
		)
	return token

async def require_user(auth_token: Annotated[AuthToken, Depends(require_auth_token)]) -> User:
	user = await auth_token.get_user()
	if not user:
		raise HTTPException(
			status.HTTP_401_UNAUTHORIZED, 'bmaster.auth.invalid_token',
			headers={'WWW-Authenticate': 'Bearer'}
		)
	return user

def require_permissions(*permissions: str):
	def _check(user: Annotated[User, Depends(require_user)]):
		if not user.has_permissions(*permissions):
			raise HTTPException(status.HTTP_403_FORBIDDEN, 'bmaster.auth.missing_permissions')
	return _check

async def start():
	global config, hasher
	config = AuthConfig.model_validate(configs.main_config['auth'])
	hasher = CryptContext([config.hasher.schemas], deprecated='auto')

async def authenticate_user(username: str, password: str) -> Optional[Account]:
	from bmaster.database import LocalSession
	async with LocalSession() as session, session.begin():
		user = (await session.execute(select(Account).where(Account.name == username))).unique().scalar_one_or_none()
		if not user: return None
		is_valid, new_hash = hasher.verify_and_update(password, user.password_hash)
		if new_hash: user.password = new_hash
	if is_valid: return user
	else: return None

@api.post('/auth/login_form', tags=['auth'])
async def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
	return await login(LoginRequest(
		username=form_data.username,
		password=form_data.password
	))

class LoginRequest(BaseModel):
	username: str
	password: str

@api.post('/auth/login', tags=['auth'])
async def login(req: LoginRequest) -> Token:
	service_config = config.service
	username = req.username
	password = req.password
	if not service_config.enabled:
		if username == 'root':
			raise HTTPException(
				status.HTTP_401_UNAUTHORIZED, 'bmaster.auth.login.invalid_credentials',
				headers={'WWW-Authenticate': 'Bearer'}
			)
		user = await authenticate_user(username, password)
		if not user:
			raise HTTPException(
				status.HTTP_401_UNAUTHORIZED, 'bmaster.auth.login.invalid_credentials',
				headers={'WWW-Authenticate': 'Bearer'}
			)
		auth_token = UserToken(
			user_id=user.id
		)
		return Token(
			access_token=jwt_encode(auth_token.model_dump()),
			token_type='bearer'
		)
	else:
		if username != 'root':
			raise HTTPException(
				status.HTTP_503_SERVICE_UNAVAILABLE, 'bmaster.auth.service',
				headers={'WWW-Authenticate': 'Bearer'}
			)
		if password != service_config.password:
			raise HTTPException(
				status.HTTP_401_UNAUTHORIZED, 'bmaster.auth.login.invalid_credentials',
				headers={'WWW-Authenticate': 'Bearer'}
			)
		auth_token = RootToken()
		return Token(
			access_token=jwt_encode(auth_token.model_dump()),
			token_type='bearer'
		)

@api.get('/auth/me', tags=['auth'])
async def get_me(user: Annotated[User, Depends(require_user)]) -> SerializeAsAny[UserLocalInfo]:
	return user.get_local_info()


def validate_username(name: str):
	if name == 'root': raise ValueError('Invalid name')
	return name
Username = Annotated[str, AfterValidator(validate_username)]


@api.get('/auth/accounts', tags=['auth'])
async def get_accounts() -> list[AccountInfo]:
	from bmaster.database import LocalSession
	async with LocalSession() as session:
		accounts = (await session.execute(select(Account))).unique().scalars()
	return map(Account.get_info, accounts)

@api.get('/auth/accounts/{user_id}', tags=['auth'])
async def get_account(user_id: int) -> AccountInfo:
	from bmaster.database import LocalSession
	async with LocalSession() as session:
		user = await session.get(Account, user_id)
	if not user:
		raise HTTPException(
			404, 'User not found'
		)
	return user.get_info()

class AccountCreateRequest(BaseModel):
	name: Username
	password: str
	role_ids: set[int] = Field(default_factory=lambda: set())

@api.post('/auth/accounts', tags=['auth'], dependencies=[Depends(require_permissions('bmaster.accounts.manage'))])
async def create_account(req: AccountCreateRequest) -> AccountInfo:
	from bmaster.database import LocalSession
	user = Account(
		name=req.name,
		password_hash=hasher.hash(req.password)
	)
	async with LocalSession() as session:
		async with session.begin():
			if req.role_ids:
				roles = (await session.execute(select(Role).where(Role.id.in_(req.role_ids)))).scalars().all()
				if len(roles) != len(req.role_ids):
					raise HTTPException(status.HTTP_404_NOT_FOUND, 'Some roles were not found')
				user.roles = roles
			session.add(user)
		await session.refresh(user, ['roles'])
		return user.get_info()

class AccountUpdateRequest(BaseModel):
	name: Optional[Username] = None
	password: Optional[str] = None
	role_ids: Optional[set[int]] = None

@api.patch(
	'/auth/accounts/{user_id}',
	tags=['auth'],
	dependencies=[Depends(require_permissions('bmaster.accounts.manage'))]
)
async def update_account(user_id: int, req: AccountUpdateRequest) -> AccountInfo:
	from bmaster.database import LocalSession
	async with LocalSession() as session, session.begin():
		user = await session.get(Account, user_id)
		if not user: raise HTTPException(status.HTTP_404_NOT_FOUND, 'User not found')
		new_name = req.name
		new_password = req.password
		new_role_ids = req.role_ids
		if new_role_ids is not None:
			roles = (await session.execute(select(Role).where(Role.id.in_(new_role_ids)))).scalars().all()
			if len(roles) != len(new_role_ids):
				raise HTTPException(status.HTTP_404_NOT_FOUND, 'Some roles were not found')
			user.roles = roles
		if new_name is not None: user.name = new_name
		if new_password is not None: user.set_password(new_password)
	return user.get_info()

@api.delete('/auth/accounts/{user_id}', tags=['auth'],
	dependencies=[Depends(require_permissions('bmaster.accounts.manage'))]
)
async def delete_account(user_id: int):
	from bmaster.database import LocalSession
	async with LocalSession() as session, session.begin():
		user = await session.get(Account, user_id)
		if not user: raise HTTPException(status.HTTP_404_NOT_FOUND, 'User not found')
		await session.delete(user)
	return user.get_info()

@api.get('/auth/roles', tags=['auth'])
async def get_roles() -> list[RoleInfo]:
	from bmaster.database import LocalSession
	async with LocalSession() as session:
		roles = (await session.execute(
			select(Role)
		)).scalars().all()
	return map(lambda r: r.get_info(), roles)

@api.get('/auth/roles/{role_id}', tags=['auth'])
async def get_role(role_id: int) -> RoleInfo:
	from bmaster.database import LocalSession
	async with LocalSession() as session:
		role = await session.get(Role, role_id)
		if not role: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Role not found')
	return role.get_info()

class RoleCreateRequest(BaseModel):
	name: str
	permissions: set[str] = Field(default_factory=lambda: set())

@api.post('/auth/roles', tags=['auth'], dependencies=[
	Depends(require_permissions('bmaster.roles.manage'))
])
async def create_role(req: RoleCreateRequest) -> RoleInfo:
	from bmaster.database import LocalSession
	role = Role(
		name=req.name,
		permissions=req.permissions
	)
	async with LocalSession() as session, session.begin():
		session.add(role)
	return role.get_info()

class RoleUpdateRequest(BaseModel):
	name: Optional[str] = None
	permissions: set[str] = Field(default_factory=lambda: set())

@api.patch('/auth/roles/{role_id}', tags=['auth'], dependencies=[
	Depends(require_permissions('bmaster.roles.manage'))
])
async def update_role(req: RoleUpdateRequest, role_id: int) -> RoleInfo:
	from bmaster.database import LocalSession
	
	async with LocalSession() as session, session.begin():
		role = await session.get(Role, role_id)
		if not role:
			raise HTTPException(status.HTTP_404_NOT_FOUND, 'Role not found')

		if req.name is not None:
			role.name = req.name
		if req.permissions is not None:
			role.permissions = req.permissions
	
	return role.get_info()

@api.delete('/auth/roles/{role_id}', tags=['auth'], dependencies=[
	Depends(require_permissions('bmaster.roles.manage'))
])
async def delete_role(role_id: int) -> RoleInfo:
	from bmaster.database import LocalSession
	
	async with LocalSession() as session, session.begin():
		role = await session.get(Role, role_id)
		if not role:
			raise HTTPException(status.HTTP_404_NOT_FOUND, 'Role not found')
		await session.delete(role)
	
	return role.get_info()
