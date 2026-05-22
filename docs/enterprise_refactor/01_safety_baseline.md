# Enterprise Refactor Phase -1 Safety Baseline

Execution timestamp: 2026-05-22T19:18:02+07:00

This baseline records the repository and local runtime state before the enterprise refactor continues beyond audit-only work. No functional source code was changed as part of this phase.

## Git Baseline

- Current branch: `main`
- Current commit hash: `a98ad15f1dfed13e3d5901e61df184d08513f335`
- Phase -2 commit already present: `Enterprise Refactor Phase -2: repository enterprise audit`
- Pre-existing dirty/untracked files were observed and intentionally left untouched:
  - `SYSTEM_MAP.md`
  - `kuro_backend/config.py`
  - `main.py`
  - `tests/test_telegram_hardening.py`
  - `KuroAI_Enterprise_Major_Refactor_Codex_Prompts.md`
  - `kuro-deep-research-report.md`
  - `kuro_backend/telegram_center/`

## Python Baseline

- `python3 --version`: `Python 3.10.12`
- `python --version`: unavailable in this shell (`python: command not found`)
- Installed package command: `python3 -m pip freeze`
- Installed package count: `323`

## Installed Package List

```text
acres==0.5.0
ag-ui-protocol==0.1.18
aiofile==3.9.0
aiofiles==25.1.0
aiohappyeyeballs==2.6.1
aiohttp==3.13.5
aiohttp-retry==2.9.1
aioitertools==0.13.0
aiosignal==1.4.0
aiosqlite==0.22.1
alembic==1.18.4
annotated-doc==0.0.4
annotated-types==0.7.0
annoy==1.17.3
anthropic==0.100.0
anyio==4.12.1
APScheduler==3.11.2
argcomplete==3.6.3
arize-phoenix==15.4.0
arize-phoenix-client==2.6.0
arize-phoenix-evals==3.1.0
arize-phoenix-otel==0.16.1
asgiref==3.5.0
async-timeout==4.0.3
attrs==26.1.0
Authlib==1.7.2
Automat==20.2.0
Babel==2.8.0
backports.tarfile==1.2.0
bcrypt==3.2.0
beartype==0.22.9
blinker==1.4
boto3==1.43.6
botocore==1.43.6
cachetools==7.1.1
caio==0.9.25
certifi==2026.2.25
cffi==2.0.0
chardet==4.0.0
charset-normalizer==3.4.7
ci-info==0.4.0
click==8.3.2
cloud-init==25.2
cohere==6.1.0
colorama==0.4.4
coloredlogs==15.0.1
command-not-found==0.3
configobj==5.0.6
configparser==7.2.0
constantly==15.1.0
cross-web==0.6.0
cryptography==46.0.5
cyclopts==4.11.2
dataclasses-json==0.6.7
dbus-python==1.2.18
distro==1.7.0
distro-info==1.1+ubuntu0.2
dnspython==2.8.0
docstring_parser==0.18.0
docutils==0.22.4
dotenv==0.9.9
ecdsa==0.19.2
email-validator==2.3.0
et_xmlfile==2.0.0
etelemetry==0.3.1
eval_type_backport==0.3.1
exceptiongroup==1.3.1
executing==2.2.1
fastapi==0.135.3
fastavro==1.12.2
fastembed==0.8.0
fastmcp==3.2.4
filelock==3.25.2
filetype==1.2.0
fitz==0.0.1.dev2
flatbuffers==25.12.19
frontend==0.0.3
frozenlist==1.8.0
fsspec==2026.3.0
genai-prices==0.0.59
google-ai-generativelanguage==0.6.15
google-api-core==2.30.2
google-api-python-client==2.193.0
google-auth==2.49.1
google-auth-httplib2==0.3.0
google-auth-oauthlib==1.2.4
google-genai==1.70.0
google-generativeai==0.8.6
googleapis-common-protos==1.72.0
graphql-core==3.2.8
greenlet==3.4.0
griffelib==2.0.2
groq==1.2.0
grpc-interceptor==0.15.4
grpcio==1.80.0
grpcio-status==1.71.2
h11==0.16.0
hf-xet==1.4.3
httpcore==1.0.9
httplib2==0.20.2
httpx==0.28.1
httpx-sse==0.4.3
huggingface_hub==1.9.2
humanfriendly==10.0
hyperlink==21.0.0
idna==3.3
importlib_metadata==8.7.1
importlib_resources==6.5.2
incremental==21.3.0
iniconfig==2.3.0
isodate==0.7.2
itsdangerous==2.2.0
jaraco.classes==3.4.0
jaraco.context==6.1.2
jaraco.functools==4.4.0
jeepney==0.7.1
Jinja2==3.1.6
jiter==0.14.0
jmespath==1.1.0
joblib==1.5.3
joserfc==1.6.5
jsonpatch==1.33
jsonpath-ng==1.8.0
jsonpath-python==1.1.6
jsonpointer==2.0
jsonref==1.1.0
jsonschema==4.26.0
jsonschema-path==0.4.6
jsonschema-specifications==2025.9.1
keyring==25.7.0
langchain==1.2.15
langchain-classic==1.0.3
langchain-community==0.4.1
langchain-core==1.2.26
langchain-google-genai==4.2.1
langchain-text-splitters==1.1.1
langgraph==1.1.6
langgraph-checkpoint==4.0.1
langgraph-prebuilt==1.0.9
langgraph-sdk==0.3.12
langsmith==0.7.25
lark==1.3.1
launchpadlib==1.10.16
lazr.restfulclient==0.14.4
lazr.uri==1.0.6
ldap3==2.9.1
logfire==4.32.1
logfire-api==4.32.1
loguru==0.7.3
looseversion==1.3.0
lxml==6.0.2
Mako==1.3.12
markdown-it-py==4.0.0
MarkupSafe==2.0.1
marshmallow==3.26.2
mcp==1.27.1
mdurl==0.1.2
mistralai==2.4.5
mmh3==5.2.1
more-itertools==8.10.0
mpmath==1.3.0
multidict==6.7.1
mypy_extensions==1.1.0
nemoguardrails==0.21.0
nest-asyncio==1.6.0
netifaces==0.11.0
networkx==3.4.2
nexus-rpc==1.4.0
nibabel==5.4.2
nipype==1.11.0
numpy==2.2.6
oauthlib==3.2.0
onnxruntime==1.23.2
openai==2.36.0
openapi-pydantic==0.5.1
openinference-instrumentation==0.1.49
openinference-instrumentation-openai==0.1.46
openinference-semantic-conventions==0.1.29
openpyxl==3.1.5
opentelemetry-api==1.39.1
opentelemetry-exporter-otlp==1.39.1
opentelemetry-exporter-otlp-proto-common==1.39.1
opentelemetry-exporter-otlp-proto-grpc==1.39.1
opentelemetry-exporter-otlp-proto-http==1.39.1
opentelemetry-instrumentation==0.60b1
opentelemetry-instrumentation-httpx==0.60b1
opentelemetry-proto==1.39.1
opentelemetry-sdk==1.39.1
opentelemetry-semantic-conventions==0.60b1
opentelemetry-util-http==0.60b1
orjson==3.11.8
ormsgpack==1.12.2
packaging==25.0
pandas==2.3.3
passlib==1.7.4
pathable==0.5.0
pathlib==1.0.1
pdfminer.six==20251230
pdfplumber==0.11.9
pexpect==4.8.0
pillow==12.2.0
platformdirs==4.9.6
pluggy==1.6.0
prometheus_client==0.25.0
prompt_toolkit==3.0.52
propcache==0.4.1
proto-plus==1.27.1
protobuf==5.29.6
prov==2.1.1
psutil==7.2.2
ptyprocess==0.7.0
puremagic==1.30
py-key-value-aio==0.4.4
py_rust_stemmers==0.1.5
pyarrow==24.0.0
pyasn1==0.6.3
pyasn1-modules==0.2.1
pycparser==3.0
pydantic==2.12.5
pydantic-ai==1.93.0
pydantic-ai-slim==1.93.0
pydantic-evals==1.93.0
pydantic-graph==1.93.0
pydantic-handlebars==0.1.0
pydantic-settings==2.13.1
pydantic_core==2.41.5
pydot==4.0.1
Pygments==2.20.0
PyGObject==3.42.1
PyHamcrest==2.0.2
PyJWT==2.12.1
pyOpenSSL==21.0.0
pyparsing==3.3.2
pypdf==6.9.2
PyPDF2==3.0.1
pypdfium2==5.6.0
pyperclip==1.11.0
pyrsistent==0.18.1
pyserial==3.5
pystache==0.6.8
pytest==9.0.3
python-apt==2.4.0+ubuntu4.1
python-dateutil==2.9.0.post0
python-debian==0.1.43+ubuntu1.1
python-docx==1.2.0
python-dotenv==1.2.2
python-jose==3.5.0
python-magic==0.4.24
python-multipart==0.0.22
python-telegram-bot==22.6
pytz==2022.1
pyxnat==1.6.4
PyYAML==6.0.3
rdflib==7.6.0
referencing==0.37.0
regex==2026.5.9
reportlab==4.5.0
requests==2.33.1
requests-oauthlib==2.0.0
requests-toolbelt==1.0.0
rich==14.3.3
rich-rst==1.3.2
rpds-py==0.30.0
rsa==4.9.1
s3transfer==0.17.0
scikit-learn==1.7.2
scipy==1.15.3
SecretStorage==3.3.1
service-identity==18.1.0
shellingham==1.5.4
simpleeval==1.0.7
simplejson==3.20.2
six==1.16.0
sniffio==1.3.1
sos==4.9.2
SQLAlchemy==2.0.49
sqlean.py==3.50.4.5
sse-starlette==3.4.2
ssh-import-id==5.11
starlette==1.0.0
strawberry-graphql==0.314.3
sympy==1.14.0
systemd-python==234
temporalio==1.27.0
tenacity==9.1.4
threadpoolctl==3.6.0
tiktoken==0.12.0
tokenizers==0.22.2
tomli==2.4.1
tqdm==4.67.3
traits==7.1.0
Twisted==22.1.0
typer==0.24.1
types-protobuf==6.32.1.20260221
types-requests==2.33.0.20260508
typing-inspect==0.9.0
typing-inspection==0.4.2
typing_extensions==4.15.0
tzdata==2026.1
tzlocal==5.3.1
ubuntu-drivers-common==0.0.0
ubuntu-pro-client==8001
ufw==0.36.1
unattended-upgrades==0.1
uncalled-for==0.3.2
uritemplate==4.2.0
urllib3==2.7.0
uuid_utils==0.14.1
uvicorn==0.44.0
wadllib==1.3.6
watchdog==6.0.0
watchfiles==1.1.1
wcwidth==0.6.0
websockets==16.0
wrapt==1.17.3
wsproto==1.0.0
xai-sdk==1.12.2
xkit==0.0.0
xxhash==3.6.0
yarl==1.23.0
zipp==3.23.1
zope.interface==5.4.0
zstandard==0.25.0
```

## SQLite Files Found

These files were found outside ignored backup and virtual environment directories:

```text
finance_data.db
kuro_auth.db
kuro_backend/kuro_short_term.db
kuro_chat_history.db
kuro_chromadb/chroma.sqlite3
kuro_chromadb/ingestion_center/chroma.sqlite3
kuro_compliance.db
kuro_compliance_chroma/chroma.sqlite3
kuro_finances.db
kuro_ingestion.db
kuro_intelligence.db
kuro_playground.db
kuro_short_term.db
phoenix_data/phoenix.db
```

## Runtime JSON State Files Found

```text
kuro_memory.json
master_profile.json
```

## Env-Like Files Found

Secrets were not printed or copied into this document.

```text
.env
```

## Chroma And Vector Directories Found

Virtual environment package directories were excluded from this runtime inventory.

```text
kuro_chromadb
kuro_compliance_chroma
```

## Upload And Runtime Directories Found

Virtual environment package directories were excluded from this runtime inventory.

```text
config/runtime
exports
kuro_backend/evaluation_runtime
kuro_backend/logs
kuro_backend/runtime
kuro_backend/uploaded_files
logs
phoenix_data
playground_runtime
tests/playground_runtime
uploaded_files
```

## Backup Snapshot

- Backup directory: `backups/pre-enterprise-refactor/`
- Backup size after copy: `942M`
- SQLite files copied: `14`
- Runtime JSON files copied: `2`
- `.env` backup: present as `backups/pre-enterprise-refactor/.env.backup`

Backup layout:

```text
backups/pre-enterprise-refactor/.env.backup
backups/pre-enterprise-refactor/db/finance_data.db
backups/pre-enterprise-refactor/db/kuro_auth.db
backups/pre-enterprise-refactor/db/kuro_backend/kuro_short_term.db
backups/pre-enterprise-refactor/db/kuro_chat_history.db
backups/pre-enterprise-refactor/db/kuro_chromadb/chroma.sqlite3
backups/pre-enterprise-refactor/db/kuro_chromadb/ingestion_center/chroma.sqlite3
backups/pre-enterprise-refactor/db/kuro_compliance.db
backups/pre-enterprise-refactor/db/kuro_compliance_chroma/chroma.sqlite3
backups/pre-enterprise-refactor/db/kuro_finances.db
backups/pre-enterprise-refactor/db/kuro_ingestion.db
backups/pre-enterprise-refactor/db/kuro_intelligence.db
backups/pre-enterprise-refactor/db/kuro_playground.db
backups/pre-enterprise-refactor/db/kuro_short_term.db
backups/pre-enterprise-refactor/db/phoenix_data/phoenix.db
backups/pre-enterprise-refactor/runtime_json/kuro_memory.json
backups/pre-enterprise-refactor/runtime_json/master_profile.json
```

## Ignore Guardrail

`.gitignore` already ignored `.env`, `*.db`, `backups/`, runtime JSON state files, upload folders, Phoenix data, and Chroma stores. Phase -1 added SQLite-specific ignore patterns for:

```text
*.sqlite
*.sqlite3
*.sqlite-wal
*.sqlite-shm
*.sqlite3-wal
*.sqlite3-shm
```

This keeps Chroma and other SQLite runtime files from being accidentally committed.

Legacy tracked runtime files observed during ignore verification:

```text
kuro_chromadb/chroma.sqlite3
phoenix_data/phoenix.db
```

They were not removed from the git index in this phase because phase -1 is limited to safety baseline, backups, ignore rules, and restore documentation. Any `git rm --cached` cleanup should happen only in an explicit later hygiene phase.
