"""The window's text in English and Brazilian Portuguese."""
import locale
import os

TEXTS = {
    'app': ('PSP Movie Tools', 'PSP Movie Tools'),
    'nav_tools': ('Tools', 'Ferramentas'),
    'nav_disc': ('Disc', 'Disco'),
    'nav_upscale': ('Upscale', 'Remasterizar'),
    'nav_about': ('About', 'Sobre'),
    # Tools
    'tools_title': ('Tools', 'Ferramentas'),
    'tools_intro': ('Extracting needs nothing else. Writing .mp4 files and upscaling need ffmpeg; upscaling needs '
                    'Real-ESRGAN too. Download them here: they go into the tools folder and are set up for you.',
                    'Para extrair não precisa de nada. Para gravar .mp4 e remasterizar, precisa do ffmpeg; para '
                    'remasterizar, também do Real-ESRGAN. Baixe aqui: eles vão para a pasta de ferramentas e já '
                    'ficam configurados.'),
    'ffmpeg_what': ('Reads and writes video.', 'Lê e grava vídeo.'),
    'realesrgan_what': ('The AI that upscales each frame. Runs on any graphics card with Vulkan (AMD, NVIDIA, Intel).',
                        'A IA que aumenta cada quadro. Roda em qualquer placa de vídeo com Vulkan (AMD, NVIDIA, '
                        'Intel).'),
    'found': ('Ready', 'Pronto'),
    'missing': ('Not installed', 'Não instalado'),
    'no_x264': ('This ffmpeg has no libx264 encoder: download the one here to upscale.',
                'Este ffmpeg não tem o encoder libx264: baixe o daqui para remasterizar.'),
    'models': ('{} models', '{} modelos'),
    'download': ('Download', 'Baixar'),
    'download_again': ('Download again', 'Baixar de novo'),
    'downloading': ('Downloading {}…', 'Baixando {}…'),
    'downloaded': ('{} is ready.', '{} está pronto.'),
    'no_download': ('No download for this system: install it and put it on the PATH.',
                    'Sem download para este sistema: instale e coloque no PATH.'),
    'tools_folder': ('Tools folder', 'Pasta de ferramentas'),
    'open': ('Open', 'Abrir'),
    'cancel': ('Cancel', 'Cancelar'),
    'language': ('Language', 'Idioma'),
    'language_note': ('Applies the next time the window opens.', 'Vale na próxima vez que a janela abrir.'),
    # Disc
    'disc_title': ('Disc', 'Disco'),
    'disc_intro': ('Pick the disc image of your own copy of the game. Its movies are listed here; extract the ones '
                   'you want into the output folder.',
                   'Escolha a imagem de disco da sua cópia do jogo. Os vídeos dela aparecem aqui; extraia os que '
                   'quiser para a pasta de saída.'),
    'iso': ('Disc image', 'Imagem de disco'),
    'choose_iso': ('Choose…', 'Escolher…'),
    'output': ('Output folder', 'Pasta de saída'),
    'choose_folder': ('Choose…', 'Escolher…'),
    'game': ('Game {} · {} movies', 'Jogo {} · {} vídeos'),
    'chip_movies': ('{} movies', '{} vídeos'),
    'chip_length': ('{} in all', '{} no total'),
    'chip_extracted': ('{} extracted', '{} extraídos'),
    'col_movie': ('Movie', 'Vídeo'),
    'col_length': ('Length', 'Duração'),
    'col_size': ('Size', 'Tamanho'),
    'col_audio': ('Audio', 'Áudio'),
    'col_status': ('Status', 'Situação'),
    'col_frames': ('Frames', 'Quadros'),
    'extracted': ('Extracted', 'Extraído'),
    'select_all': ('Select all', 'Marcar todos'),
    'select_none': ('Select none', 'Desmarcar'),
    'extract': ('Extract selected', 'Extrair selecionados'),
    'extracting': ('Extracting {} ({}/{})…', 'Extraindo {} ({}/{})…'),
    'extracted_n': ('{} movies extracted.', '{} vídeos extraídos.'),
    'no_ffmpeg_mp4': ('No ffmpeg: writing .264 files only. Download ffmpeg in Tools for .mp4.',
                      'Sem ffmpeg: só arquivos .264. Baixe o ffmpeg em Ferramentas para ter .mp4.'),
    'pick_iso_first': ('Choose a disc image first.', 'Escolha uma imagem de disco primeiro.'),
    'nothing_selected': ('Select at least one movie.', 'Marque pelo menos um vídeo.'),
    # Upscale
    'up_title': ('Upscale', 'Remasterizar'),
    'up_intro': ('Movies extracted into the output folder. The upscaled copies keep the frame rate and the frame '
                 'count, so they can replace the originals in a port, and go into the remaster folder.',
                 'Vídeos extraídos na pasta de saída. As cópias remasterizadas mantêm o fps e o número de quadros, '
                 'para substituir os originais num port, e vão para a pasta remaster.'),
    'model': ('Model', 'Modelo'),
    'model_realesrgan-x4plus': ('Quality: realesrgan-x4plus (recommended)', 'Qualidade: realesrgan-x4plus (recomendado)'),
    'model_realesr-animevideov3-x4': ('Fast: realesr-animevideov3 (about 10 times faster)',
                                      'Rápido: realesr-animevideov3 (umas 10 vezes mais rápido)'),
    'model_realesrgan-x4plus-anime': ('Anime: realesrgan-x4plus-anime', 'Anime: realesrgan-x4plus-anime'),
    'resolution': ('Resolution', 'Resolução'),
    'res_1088': ('1920 × 1088 (Full HD)', '1920 × 1088 (Full HD)'),
    'res_1632': ('2880 × 1632', '2880 × 1632'),
    'res_2176': ('3840 × 2176 (4K)', '3840 × 2176 (4K)'),
    'quality': ('Video quality (lower is better)', 'Qualidade do vídeo (menor é melhor)'),
    'pending': ('Not yet', 'Pendente'),
    'partial': ('Stopped at {}%', 'Parou em {}%'),
    'done': ('Upscaled', 'Remasterizado'),
    'refresh': ('Refresh', 'Atualizar'),
    'preview': ('Preview…', 'Pré-visualizar…'),
    'upscale': ('Upscale selected', 'Remasterizar selecionados'),
    'open_remaster': ('Open remaster folder', 'Abrir pasta remaster'),
    'upscaling': ('{} · {}/{} frames · {:.2f} frames/s · about {} left',
                  '{} · {}/{} quadros · {:.2f} quadros/s · faltam uns {}'),
    'upscaling_queue': ('Movie {} of {}', 'Vídeo {} de {}'),
    'upscaled_n': ('{} movies upscaled.', '{} vídeos remasterizados.'),
    'need_tools': ('Download ffmpeg and Real-ESRGAN in Tools first.',
                   'Baixe o ffmpeg e o Real-ESRGAN em Ferramentas primeiro.'),
    'no_extracted': ('No extracted movies in the output folder yet: extract some in Disc.',
                     'Ainda não há vídeos extraídos na pasta de saída: extraia em Disco.'),
    'minutes': ('{} min', '{} min'),
    'hours': ('{} h {} min', '{} h {} min'),
    'cancelled': ('Stopped. Upscaling goes on from the last finished block next time.',
                  'Parado. Na próxima vez, a remasterização continua do último bloco pronto.'),
    # Preview
    'preview_title': ('Preview: {}', 'Pré-visualização: {}'),
    'frame': ('Frame', 'Quadro'),
    'update': ('Update', 'Atualizar'),
    'original': ('Original, stretched', 'Original, esticado'),
    'remaster': ('Upscaled ({})', 'Remasterizado ({})'),
    'previewing': ('Upscaling one frame…', 'Remasterizando um quadro…'),
    'pick_one': ('Select one movie to preview.', 'Marque um vídeo para pré-visualizar.'),
    # About
    'about_title': ('About', 'Sobre'),
    'about_text': ('Lists, extracts and upscales the cutscene movies of a PSP game from your own disc image. It '
                   'works with any game that keeps its movies as PSMF files (.pmf).\n\n'
                   'Nothing from any game comes with this tool, and nothing is sent anywhere: it reads the disc '
                   'image you choose and writes to folders you choose. Keep what you extract and upscale to '
                   'yourself.\n\n'
                   'Upscaling uses Real-ESRGAN (BSD-3-Clause) through realesrgan-ncnn-vulkan, and ffmpeg. The '
                   'window uses Dear PyGui (MIT).',
                   'Lista, extrai e remasteriza os vídeos (cutscenes) de um jogo de PSP a partir da sua própria '
                   'imagem de disco. Funciona com qualquer jogo que guarde os vídeos como arquivos PSMF (.pmf).\n\n'
                   'Nenhum conteúdo de jogo vem com esta ferramenta, e nada é enviado a lugar nenhum: ela lê a '
                   'imagem de disco que você escolhe e grava nas pastas que você escolhe. Guarde o que extrair e '
                   'remasterizar só para você.\n\n'
                   'A remasterização usa o Real-ESRGAN (BSD-3-Clause), pelo realesrgan-ncnn-vulkan, e o ffmpeg. A '
                   'janela usa o Dear PyGui (MIT).'),
    'busy': ('Something is already running.', 'Já tem algo em andamento.'),
    'error': ('Error: {}', 'Erro: {}'),
}

LANGUAGES = {'en': 'English', 'pt': 'Português (Brasil)'}


def system_language():
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = os.environ.get(name, '')
        if value:
            return 'pt' if value.lower().startswith('pt') else 'en'
    try:
        if os.name == 'nt':
            import ctypes
            lang = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return 'pt' if lang == 0x16 else 'en'
        code = locale.getlocale()[0] or ''
        return 'pt' if code.lower().startswith('pt') else 'en'
    except (OSError, ValueError, AttributeError):
        return 'en'


class Texts:
    def __init__(self, language=''):
        self.language = language if language in LANGUAGES else system_language()
        self.index = 1 if self.language == 'pt' else 0

    def __call__(self, key, *args):
        text = TEXTS[key][self.index]
        return text.format(*args) if args else text
