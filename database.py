# настройки под postgres, если надо будет 

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from core.config import settings

# "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

engine = create_async_engine(
    settings.db_settings.db_url.render_as_string(hide_password=False),
    echo=settings.db_settings.db_echo,
    pool_pre_ping=True,       # проверяет живо ли соединение перед запросом
    pool_size=10,             # Базовый размер пула соединений
    max_overflow=20,          # Допустимый всплеск нагрузки
    pool_recycle=300, 
    )

new_session = async_sessionmaker(
    bind=engine, 
    expire_on_commit=False,
    # autoflush=False,
    )


async def get_session():
    async with new_session() as sess:
        try:
            yield sess
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

# async def setup_db():
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)


    
