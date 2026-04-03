# WhatsApp Recruiter

Aplicacao em Python para:

- abrir o WhatsApp Web com Selenium;
- percorrer as conversas visiveis na barra lateral;
- usar a busca da propria conversa para localizar termos como `curriculo`, `nome completo`, `crm` e `especialidade`;
- consolidar dados textuais encontrados ao longo da conversa inteira;
- se faltar informacao, localizar e baixar o PDF anexado;
- extrair texto do PDF com OCR quando necessario;
- converter os dados extraidos para JSON e XLSX.

## Fluxo

1. O Selenium abre o WhatsApp Web.
2. Voce escaneia o QR Code na primeira execucao.
3. A automacao percorre conversa por conversa no sidebar lateral.
4. O sistema tenta abrir a busca interna da conversa para localizar mensagens por palavras-chave.
5. Se a busca interna nao estiver disponivel, ele usa as mensagens recentes visiveis como fallback.
6. O termo passado em `--search` e as `--keywords` sao usados para localizar mensagens/anexos relevantes.
7. O parser tenta encontrar `nome`, `crm`, `especializacao`, `telefone`, `email`, `indicacao`, `cidade` e `uf`.
8. Se os dados nao estiverem so na mensagem, o bot tenta localizar um PDF, fazer o download e extrair o texto.
9. O resultado final por conversa e consolidado em um unico cadastro antes de exportar.
8. O resultado final e salvo em:
   - `output/recruiters.json`
   - `output/recruiters.xlsx`

## Requisitos no Windows

Instale:

- Python 3.11+
- Mozilla Firefox
- Tesseract OCR
- Poppler for Windows

Depois configure os caminhos em `.env`.

## Instalacao

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Crie um arquivo `.env` na raiz:

```env
BROWSER=firefox
WHATSAPP_PROFILE_DIR=C:\Users\USER\AppData\Roaming\Mozilla\Firefox\Profiles
WHATSAPP_PROFILE_NAME=xxxxxxx.default-release
WHATSAPP_DOWNLOAD_DIR=C:\Users\USER\Downloads\whatsapp_recruiter\downloads
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\poppler\Library\bin
HEADLESS=true
```

Valores aceitos em `BROWSER`:

- `firefox`
- `chrome`
- `safari`

## Uso

Exemplo:

```powershell
python main.py --search "curriculum" --limit 30 --chat-limit 50
```

Ou usando o atalho do projeto, ja em headless por padrao:

```powershell
.\run.ps1 -Search "curriculum"
```

Argumentos:

- `--search`: termo usado para localizar mensagens/anexos durante a varredura das conversas.
- `--limit`: quantidade maxima de evidencias relevantes por conversa.
- `--chat-limit`: quantidade maxima de conversas a percorrer na barra lateral.
- `--output`: nome base do arquivo de saida.
- `-Headless`: no `run.ps1`, controla se o navegador escolhido roda sem interface. O padrao e `true`.

## Observacoes importantes

- Os seletores do WhatsApp Web podem mudar com o tempo. Se isso acontecer, ajuste o arquivo `src/whatsapp_recruiter/whatsapp/client.py`.
- Alguns PDFs ja possuem texto pesquisavel; nesse caso o sistema tenta extrair sem OCR antes.
- Para PDFs escaneados, o OCR usa `pdf2image + pytesseract`.
- O bot esta preparado para curriculos em portugues, mas os regex podem ser refinados para o seu padrao real.
- Para `firefox`, use `WHATSAPP_PROFILE_DIR` apontando para `Mozilla\Firefox\Profiles` e `WHATSAPP_PROFILE_NAME` com a pasta do perfil desejado, como `xxxxxxx.default-release`.
- Para `chrome`, use `WHATSAPP_PROFILE_DIR` apontando para `Chrome\User Data` e `WHATSAPP_PROFILE_NAME` com o perfil desejado, como `Default`.
- Para `safari`, este projeto usa o perfil padrao do sistema e ignora `WHATSAPP_PROFILE_NAME`.
- Se o navegador escolhido ja estiver aberto nesse mesmo perfil, feche-o antes de rodar a automacao.
- Se o WhatsApp pedir novo QR Code ou revalidacao de sessao, rode temporariamente com interface: `.\run.ps1 -Headless $false`.
- `safari` so funciona no macOS e neste projeto deve rodar com `HEADLESS=false`.
