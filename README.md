# Флоу веб-сервиса

Цепочка Router -> AssistantService -> AssistantRepository -> AsyncSession (Postgres) собрана через Depends
(это архитектура, содержимое классов и роутеры можно менять)

core/config.py - настройки окружения бд
database_models - набросок таблиц
database - движок бд

Для исп. llm через используется контроллер controllers.py,
то есть он используется и для api веб-приложения как depends в services.py и для скрипта solution.py

Теперь скрипт разбит по файлам solution.py - точка входа, retriever.py,
config.py models.py llm_client.py controllers.py;
requirements.txt - их пока лучше не менять
