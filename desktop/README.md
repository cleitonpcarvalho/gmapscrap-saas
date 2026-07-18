# GmapScrap Desktop

App local para rodar a busca do Google Maps no computador e salvar os resultados pela API de produção.

## Rodar no Mac

Crie um ambiente Python e instale as dependências:

```bash
python3 -m venv .venv-desktop
source .venv-desktop/bin/activate
pip install -r desktop/requirements.txt
```

Depois rode:

```bash
python -m desktop.app
```

O app lê `APP_USERNAME` e `APP_PASSWORD` do `.env` local e usa `https://api.automasoluct.com.br` por padrão.

Para desenvolvimento local, use:

```bash
GMAPSCRAP_API_BASE_URL=http://localhost:8000 python -m desktop.app
```
