# psp-movie-tools

[English](README.md) · **Português (Brasil)**

Lista e extrai os vídeos (cutscenes) de um jogo de PSP a partir da **sua própria** imagem de disco, para você assistir, ou remasterizar e colocar de volta num port que aceite vídeos de substituição. Funciona com qualquer jogo que guarde os vídeos como arquivos PSMF (`.pmf`), o que é o caso da maioria.

> [!IMPORTANT]
> Este repositório não contém nenhum dado de jogo. A ferramenta só lê uma imagem de disco que você fornece e grava os vídeos numa pasta que você escolhe. Guarde o que extrair só para você.

## A janela

```bash
pip install -r requirements.txt     # Dear PyGui, uma vez
python psp_movies.py gui            # ou duplo clique em "PSP Movie Tools.pyw" no Windows
```

1. **Ferramentas**: baixe o ffmpeg e o Real-ESRGAN com um clique (versões fixas, conferidas pelo SHA-256, descompactadas na pasta de ferramentas do app e já configuradas). Os que já estiverem instalados são encontrados.
2. **Disco**: escolha a sua imagem de disco e uma pasta de saída; os vídeos aparecem com duração, tamanho e faixas de áudio; extraia os que marcar.
3. **Remasterizar**: escolha o modelo, a resolução e a qualidade; **pré-visualize** um quadro antes e depois; remasterize os vídeos marcados, com progresso e tempo restante; pare e continue depois.

Em inglês e português do Brasil. As configurações ficam guardadas por usuário.

## Linha de comando

Python 3.9 ou mais novo, mais nada. O [ffmpeg](https://ffmpeg.org/) no PATH é opcional: com ele, cada vídeo também sai como `.mp4` (o mesmo vídeo, sem recodificar), que é o que a maioria das ferramentas de vídeo e de remasterização com IA abre.

```bash
python psp_movies.py list    "Meu Jogo.iso"
python psp_movies.py extract "Meu Jogo.iso" videos/                    # todos os vídeos
python psp_movies.py extract "Meu Jogo.iso" videos/ --only R6_INTRO    # só um
```

Para cada vídeo, o `extract` grava:

| Arquivo | O que é |
| --- | --- |
| `NOME.264` | o vídeo exatamente como está no disco (H.264) |
| `NOME.mp4` | o mesmo vídeo num arquivo MP4, se o ffmpeg estiver instalado |
| `NOME.json` | tamanho, fps, número de quadros e tempos: o que é preciso para colocar a versão nova de volta |

O áudio (ATRAC3plus, em geral uma faixa por idioma) fica no disco: o vídeo novo substitui só a imagem, e o jogo continua tocando o próprio som, sincronizado.

## Remasterizando um vídeo

O `upscale` faz isso com o `realesrgan-ncnn-vulkan` do [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (`python psp_movies.py download realesrgan`, ou a página Ferramentas; ele roda em qualquer placa com Vulkan, AMD inclusive) e o ffmpeg:

```bash
python psp_movies.py upscale videos/R6_INTRO.mp4 remaster/R6_INTRO.mp4 
```

Ele mantém o fps e o número de quadros, grava 1920x1088 por padrão (`--height`) e trabalha em blocos de 300 quadros, então o disco guarda um bloco de imagens por vez; se parar no meio, rode de novo e ele continua do último bloco pronto. Modelos: `realesrgan-x4plus` (o padrão, o melhor para vídeo renderizado; cerca de 1 quadro por segundo numa Radeon RX 7600) ou `realesr-animevideov3` (umas 10 vezes mais rápido, mais suave e com menos detalhe).

Ou remasterize o `NOME.mp4` em outra ferramenta:

1. Extraia e remasterize o `NOME.mp4` na ferramenta que preferir. Mantenha **o fps e o número de quadros** (`NOME.json`): o vídeo novo é mostrado quadro a quadro junto com o áudio original do jogo.
2. Mantenha a proporção 480:272, em qualquer tamanho (por exemplo 1920×1088 ou 3840×2176).
3. Coloque o resultado onde o port procura vídeos de substituição (no Sparta: planejado, veja a documentação dele).

## Licença

MIT ([LICENSE](LICENSE)).
