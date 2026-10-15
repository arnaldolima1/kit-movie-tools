# psp-movie-tools

[English](README.md) · **Português (Brasil)**

Lista e extrai os vídeos (cutscenes) de um jogo de PSP a partir da **sua própria** imagem de disco, para você assistir, ou remasterizar e colocar de volta num port que aceite vídeos de substituição. Funciona com qualquer jogo que guarde os vídeos como arquivos PSMF (`.pmf`), o que é o caso da maioria.

> [!IMPORTANT]
> Este repositório não contém nenhum dado de jogo. A ferramenta só lê uma imagem de disco que você fornece e grava os vídeos numa pasta que você escolhe. Guarde o que extrair só para você.

## Uso

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

1. Extraia e remasterize o `NOME.mp4` na ferramenta que preferir. Mantenha **o fps e o número de quadros** (`NOME.json`): o vídeo novo é mostrado quadro a quadro junto com o áudio original do jogo.
2. Mantenha a proporção 480:272, em qualquer tamanho (por exemplo 1920×1088 ou 3840×2176).
3. Coloque o resultado onde o port procura vídeos de substituição (no Sparta: planejado, veja a documentação dele).

## Licença

MIT ([LICENSE](LICENSE)).
