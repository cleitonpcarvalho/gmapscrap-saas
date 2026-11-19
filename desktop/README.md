# GmapScrap Desktop

App local para rodar a busca do Google Maps no computador e salvar os resultados pela API de produção.

O campo **Nicho** sugere os nichos cadastrados na aplicação web e permite buscar
por parte do nome. Use **Atualizar nichos** para recarregar ou **Cadastrar nicho**
para salvar um novo nome. O cadastro é independente do histórico e as buscas
continuam aceitando texto livre. Veja [gestão de nichos](../docs/niche-management.md)
para os endpoints e a migração necessária no backend.

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

## Gerar aplicativo macOS

O app empacotado procura credenciais em `~/.gmapscrap-desktop.env`, para abrir pelo Finder sem depender do Terminal:

```env
APP_USERNAME=seu-usuario
APP_PASSWORD=sua-senha
GMAPSCRAP_API_BASE_URL=https://api.automasoluct.com.br
```

Com o ambiente de build preparado em `/tmp/gmapscrap-macos-build-venv`, rode:

```bash
PYTHON_BIN=/tmp/gmapscrap-macos-build-venv/bin/python desktop/build_macos_app.sh
```

O aplicativo fica em `desktop/dist/GmapScrap.app`.
