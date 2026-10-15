"""The window: tools, disc, upscale and about pages. Work runs on a thread;
it hands the window what to show through a queue that the frame loop
empties."""
import json
import os
import queue
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import dearpygui.dearpygui as dpg

from . import __version__, tools
from .extract import extract_movie, list_movies
from .i18n import LANGUAGES, Texts
from .iso import Iso
from .extract import video_bytes
from .preview import preview
from .thumbs import THUMB_SIZE, as_floats, cached, frame_rgba
from .upscale import upscale_movie

# A deep blue palette.
BACKGROUND = (0x0D, 0x12, 0x1A)
SIDEBAR = (0x09, 0x0D, 0x13)
CARD = (0x14, 0x1B, 0x27)
FIELD = (0x1C, 0x26, 0x36)
FIELD_HOVER = (0x24, 0x31, 0x45)
LINE = (0x26, 0x32, 0x45)
ACCENT = (0x2F, 0x6F, 0xED)
ACCENT_BRIGHT = (0x5B, 0x9B, 0xFF)
ACCENT_DARK = (0x1F, 0x4F, 0xB5)
TEXT = (0xE6, 0xEC, 0xF5)
TEXT_DIM = (0x8B, 0x97, 0xA8)
GOOD = (0x4E, 0xD1, 0x8B)
WARN = (0xF2, 0xB5, 0x4A)
BAD = (0xF0, 0x6A, 0x6A)

PAGES = ('tools', 'disc', 'upscale', 'about')
MODELS = ('realesrgan-x4plus', 'realesr-animevideov3-x4', 'realesrgan-x4plus-anime')
HEIGHTS = (1088, 1632, 2176)
PREVIEW_SIZE = (540, 306)
VIEW_SIZE = (360, 204)               # a frame in the movie viewer
VIEW_AT = (0.10, 0.35, 0.60, 0.85)   # where in the movie its four frames are
FPS = 30000 / 1001


def font_file(bold=False):
    windows = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    candidates = ([windows / 'segoeuib.ttf', windows / 'seguisb.ttf'] if bold else []) + [
        windows / 'segoeui.ttf', Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
        Path('/Library/Fonts/Arial.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/TTF/DejaVuSans.ttf')]
    return next((p for p in candidates if p.is_file()), None)


def shorten(text, size):
    """A long path with its middle cut out."""
    return text if len(text) <= size else text[:size // 2 - 1] + '…' + text[-(size // 2):]


def duration_text(t, seconds):
    minutes = int(seconds // 60 + 0.5)
    return t('hours', minutes // 60, minutes % 60) if minutes >= 60 else t('minutes', max(minutes, 1))


def centred(width, height):
    """Where a window of this size sits in the middle of the app's window."""
    return [max(0, (dpg.get_viewport_client_width() - width) // 2),
            max(0, (dpg.get_viewport_client_height() - height) // 2)]


def clock(seconds):
    return f'{int(seconds // 60)}:{int(seconds % 60):02d}'


class App:
    def __init__(self):
        self.settings = tools.load_settings()
        self.t = Texts(self.settings.get('language', ''))
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = None
        self.page = 'disc' if tools.find_ffmpeg(self.settings)[0] else 'tools'
        self.movies = []
        self.game = ''
        self.disc_checks = {}
        self.extracted = []
        self.upscale_checks = {}
        self.preview_textures = None
        self.preview_movie = None
        self.ready = False
        self.fonts = {}
        self.themes = {}
        self.blank_thumb = None
        self.thumb_textures = {}   # (where, name) -> texture
        self.thumb_buttons = {}    # (where, name) -> image button
        self.thumb_generation = 0
        self.view_textures = None

    # -- threads -------------------------------------------------------------

    def post(self, function):
        self.events.put(function)

    def start(self, kind, work):
        if self.busy:
            self.message(self.t('busy'), 'bad')
            return
        self.busy = kind
        self.cancel.clear()
        self.update_buttons()

        def body():
            try:
                work()
            except tools.Cancelled:
                self.post(lambda: self.message(self.t('cancelled') if kind == 'upscale' else '', 'warn'))
            except Exception as error:  # shown to the user, who can do something about it
                self.post(lambda error=error: self.message(self.t('error', error), 'bad'))
            finally:
                self.post(self.finish)

        threading.Thread(target=body, daemon=True).start()

    def finish(self):
        self.busy = None
        self.update_buttons()
        self.refresh_tools()
        self.refresh_extracted()
        for bar in ('download_bar', 'disc_bar', 'up_bar', 'up_movie_bar'):
            if dpg.does_item_exist(bar):
                dpg.configure_item(bar, show=False)

    # -- look ----------------------------------------------------------------

    def build_fonts(self):
        regular, bold = font_file(), font_file(bold=True)
        if regular is None:
            return
        with dpg.font_registry():
            self.fonts['body'] = dpg.add_font(str(regular), 18)
            self.fonts['small'] = dpg.add_font(str(regular), 15)
            self.fonts['title'] = dpg.add_font(str(bold or regular), 30)
            self.fonts['section'] = dpg.add_font(str(bold or regular), 19)
            self.fonts['logo'] = dpg.add_font(str(bold or regular), 22)
        dpg.bind_font(self.fonts['body'])

    def font(self, item, name):
        if name in self.fonts:
            dpg.bind_item_font(item, self.fonts[name])
        return item

    def build_theme(self):
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvAll):
                for key, value in {
                    dpg.mvThemeCol_WindowBg: BACKGROUND, dpg.mvThemeCol_ChildBg: (0, 0, 0, 0),
                    dpg.mvThemeCol_PopupBg: CARD, dpg.mvThemeCol_Text: TEXT, dpg.mvThemeCol_TextDisabled: TEXT_DIM,
                    dpg.mvThemeCol_Border: LINE, dpg.mvThemeCol_FrameBg: FIELD,
                    dpg.mvThemeCol_FrameBgHovered: FIELD_HOVER, dpg.mvThemeCol_FrameBgActive: FIELD_HOVER,
                    dpg.mvThemeCol_Button: ACCENT, dpg.mvThemeCol_ButtonHovered: ACCENT_BRIGHT,
                    dpg.mvThemeCol_ButtonActive: ACCENT_DARK, dpg.mvThemeCol_Header: (*ACCENT, 90),
                    dpg.mvThemeCol_HeaderHovered: (*ACCENT, 60), dpg.mvThemeCol_HeaderActive: (*ACCENT, 120),
                    dpg.mvThemeCol_CheckMark: ACCENT_BRIGHT, dpg.mvThemeCol_SliderGrab: ACCENT_BRIGHT,
                    dpg.mvThemeCol_SliderGrabActive: ACCENT_BRIGHT, dpg.mvThemeCol_PlotHistogram: ACCENT,
                    dpg.mvThemeCol_TableHeaderBg: (0x18, 0x21, 0x2F), dpg.mvThemeCol_TableRowBg: (0, 0, 0, 0),
                    dpg.mvThemeCol_TableRowBgAlt: (255, 255, 255, 6), dpg.mvThemeCol_TableBorderLight: LINE,
                    dpg.mvThemeCol_TableBorderStrong: LINE, dpg.mvThemeCol_ScrollbarBg: (0, 0, 0, 0),
                    dpg.mvThemeCol_ScrollbarGrab: LINE, dpg.mvThemeCol_ScrollbarGrabHovered: FIELD_HOVER,
                    dpg.mvThemeCol_TitleBg: CARD, dpg.mvThemeCol_TitleBgActive: CARD,
                    dpg.mvThemeCol_Separator: LINE, dpg.mvThemeCol_ModalWindowDimBg: (0, 0, 0, 150),
                }.items():
                    dpg.add_theme_color(key, value)
                for key, value in {dpg.mvStyleVar_FrameRounding: 8, dpg.mvStyleVar_ChildRounding: 14,
                                   dpg.mvStyleVar_WindowRounding: 14, dpg.mvStyleVar_GrabRounding: 8,
                                   dpg.mvStyleVar_PopupRounding: 10, dpg.mvStyleVar_ScrollbarRounding: 8,
                                   dpg.mvStyleVar_WindowBorderSize: 0, dpg.mvStyleVar_ChildBorderSize: 0,
                                   dpg.mvStyleVar_FrameBorderSize: 0, dpg.mvStyleVar_ScrollbarSize: 10,
                                   dpg.mvStyleVar_GrabMinSize: 14}.items():
                    dpg.add_theme_style(key, value)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 14, 9)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 10)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 26, 24)
                dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 12, 8)
            with dpg.theme_component(dpg.mvButton, enabled_state=False):
                dpg.add_theme_color(dpg.mvThemeCol_Button, LINE)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, LINE)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, LINE)
                dpg.add_theme_color(dpg.mvThemeCol_Text, TEXT_DIM)
        dpg.bind_theme(theme)

        def make(name, colors=(), styles=(), component=dpg.mvAll):
            with dpg.theme() as made:
                with dpg.theme_component(component):
                    for key, value in colors:
                        dpg.add_theme_color(key, value)
                    for key, *value in styles:
                        dpg.add_theme_style(key, *value)
            self.themes[name] = made

        make('sidebar', [(dpg.mvThemeCol_ChildBg, SIDEBAR)],
             [(dpg.mvStyleVar_ChildRounding, 0), (dpg.mvStyleVar_WindowPadding, 20, 28)])
        make('flush', styles=[(dpg.mvStyleVar_WindowPadding, 0, 0)])
        make('content', styles=[(dpg.mvStyleVar_WindowPadding, 30, 26)])
        make('card', [(dpg.mvThemeCol_ChildBg, CARD)], [(dpg.mvStyleVar_WindowPadding, 22, 18)])
        make('nav', [(dpg.mvThemeCol_Button, (0, 0, 0, 0)), (dpg.mvThemeCol_ButtonHovered, (255, 255, 255, 12)),
                     (dpg.mvThemeCol_ButtonActive, (255, 255, 255, 20)), (dpg.mvThemeCol_Text, TEXT_DIM)],
             [(dpg.mvStyleVar_ButtonTextAlign, 0.0, 0.5), (dpg.mvStyleVar_FrameRounding, 10)], dpg.mvButton)
        make('nav_on', [(dpg.mvThemeCol_Button, (*ACCENT, 50)), (dpg.mvThemeCol_ButtonHovered, (*ACCENT, 70)),
                        (dpg.mvThemeCol_ButtonActive, (*ACCENT, 90)), (dpg.mvThemeCol_Text, TEXT)],
             [(dpg.mvStyleVar_ButtonTextAlign, 0.0, 0.5), (dpg.mvStyleVar_FrameRounding, 10)], dpg.mvButton)
        make('quiet', [(dpg.mvThemeCol_Button, FIELD), (dpg.mvThemeCol_ButtonHovered, FIELD_HOVER),
                       (dpg.mvThemeCol_ButtonActive, LINE)], component=dpg.mvButton)
        make('danger', [(dpg.mvThemeCol_Button, (0x5A, 0x22, 0x28)), (dpg.mvThemeCol_ButtonHovered, (0x7A, 0x2C, 0x33)),
                        (dpg.mvThemeCol_ButtonActive, (0x8A, 0x33, 0x3B))], component=dpg.mvButton)
        for name, color in (('chip', ACCENT), ('chip_good', GOOD), ('chip_bad', BAD), ('chip_warn', WARN)):
            make(name, [(dpg.mvThemeCol_Button, (*color, 38)), (dpg.mvThemeCol_ButtonHovered, (*color, 38)),
                        (dpg.mvThemeCol_ButtonActive, (*color, 38)), (dpg.mvThemeCol_Text, color)],
                 [(dpg.mvStyleVar_FrameRounding, 20), (dpg.mvStyleVar_FramePadding, 12, 4)], dpg.mvButton)
        make('tight', styles=[(dpg.mvStyleVar_ItemSpacing, 8, 3), (dpg.mvStyleVar_CellPadding, 0, 3)])
        make('thumb', [(dpg.mvThemeCol_Button, (0, 0, 0, 0)), (dpg.mvThemeCol_ButtonHovered, (*ACCENT, 120)),
                       (dpg.mvThemeCol_ButtonActive, ACCENT)],
             [(dpg.mvStyleVar_FramePadding, 2, 2), (dpg.mvStyleVar_FrameRounding, 6)], dpg.mvImageButton)
        make('bar', [(dpg.mvThemeCol_FrameBg, FIELD), (dpg.mvThemeCol_PlotHistogram, ACCENT)],
             [(dpg.mvStyleVar_FrameRounding, 20)], dpg.mvProgressBar)
        make('preview', [(dpg.mvThemeCol_WindowBg, CARD)], [(dpg.mvStyleVar_WindowPadding, 22, 18)])

    def theme(self, item, name):
        dpg.bind_item_theme(item, self.themes[name])
        return item

    # -- small pieces --------------------------------------------------------

    @contextmanager
    def card(self, height=0, tag=None):
        kwargs = {'tag': tag} if tag else {}
        with dpg.child_window(height=height, border=False, no_scrollbar=True, auto_resize_y=height == 0,
                              always_use_window_padding=True, **kwargs) as item:
            yield item
        self.theme(item, 'card')

    def heading(self, key, intro_key):
        self.font(dpg.add_text(self.t(key), color=TEXT), 'title')
        dpg.add_text(self.t(intro_key), wrap=880, color=TEXT_DIM)
        dpg.add_spacer(height=6)

    def section(self, text):
        return self.font(dpg.add_text(text, color=TEXT), 'section')

    def label(self, text):
        return self.font(dpg.add_text(text, color=TEXT_DIM), 'small')

    def quiet(self, label, callback, **kwargs):
        return self.theme(dpg.add_button(label=label, callback=callback, **kwargs), 'quiet')

    def chip(self, text, kind='chip', **kwargs):
        return self.font(self.theme(dpg.add_button(label=text, **kwargs), kind), 'small')

    def set_chip(self, tag, text, kind):
        dpg.configure_item(tag, label=text)
        self.theme(tag, kind)

    def bar(self, tag, **kwargs):
        kwargs.setdefault('width', -1)
        return self.theme(dpg.add_progress_bar(tag=tag, show=False, **kwargs), 'bar')

    def message(self, text, kind=''):
        if dpg.does_item_exist('status'):
            dpg.set_value('status', text)
            dpg.configure_item('status', color={'bad': BAD, 'warn': WARN, 'good': GOOD}.get(kind, TEXT_DIM))

    def show_page(self, page):
        self.page = page
        for name in PAGES:
            dpg.configure_item(f'page_{name}', show=name == page)
            self.theme(f'nav_{name}', 'nav_on' if name == page else 'nav')
        if page == 'upscale':
            self.refresh_extracted()

    def update_buttons(self):
        busy = self.busy is not None
        for tag in ('download_ffmpeg', 'download_realesrgan', 'choose_iso', 'extract', 'upscale', 'preview',
                    'preview_update'):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=not busy)
        for tag in ('download_cancel', 'disc_cancel', 'up_cancel'):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=busy)

    def save(self):
        tools.save_settings(self.settings)

    # -- window --------------------------------------------------------------

    def build(self):
        t = self.t
        with dpg.window(tag='main', no_scrollbar=True):
            with dpg.group(horizontal=True, horizontal_spacing=0):
                with dpg.child_window(width=250, tag='sidebar', border=False, no_scrollbar=True,
                                      always_use_window_padding=True):
                    with dpg.group(horizontal=True):
                        self.font(dpg.add_text('Kit', color=ACCENT_BRIGHT), 'logo')
                        self.font(dpg.add_text('Movie Tools', color=TEXT), 'logo')
                    self.font(dpg.add_text(f'v{__version__}', color=TEXT_DIM), 'small')
                    dpg.add_spacer(height=22)
                    for number, page in enumerate(PAGES, start=1):
                        prefix = f'  {number}   ' if page != 'about' else '  i    '
                        dpg.add_button(label=prefix + t(f'nav_{page}'), tag=f'nav_{page}', width=-1, height=46,
                                       callback=lambda s, a, u: self.show_page(u), user_data=page)
                    dpg.add_spacer(height=24)
                    dpg.add_separator()
                    dpg.add_spacer(height=6)
                    self.label(t('tools_title'))
                    self.chip('', tag='sidebar_ffmpeg', width=-1)
                    self.chip('', tag='sidebar_realesrgan', width=-1)
                self.theme('sidebar', 'sidebar')
                with dpg.child_window(tag='content_area', border=False, no_scrollbar=True,
                                      always_use_window_padding=True):
                    with dpg.child_window(tag='content', border=False, height=-40):
                        self.build_tools_page()
                        self.build_disc_page()
                        self.build_upscale_page()
                        self.build_about_page()
                    with dpg.group(horizontal=True):
                        self.font(dpg.add_text('', tag='status', color=TEXT_DIM), 'small')
                        self.font(dpg.add_text('', tag='thumb_status', color=ACCENT_BRIGHT), 'small')
        self.theme('main', 'flush')
        self.theme('content_area', 'content')
        self.build_dialogs()
        self.show_page(self.page)
        self.refresh_tools()
        self.update_buttons()
        if self.settings.get('iso') and Path(self.settings['iso']).is_file():
            self.load_iso(self.settings['iso'])

    def build_dialogs(self):
        with dpg.file_dialog(directory_selector=False, show=False, callback=self.on_iso_chosen, tag='iso_dialog',
                             width=860, height=540, modal=True,
                             default_path=str(Path(self.settings['iso']).parent) if self.settings.get('iso')
                             else str(Path.home())):
            dpg.add_file_extension('.iso', color=ACCENT_BRIGHT)
            dpg.add_file_extension('.*')
        dpg.add_file_dialog(directory_selector=True, show=False, callback=self.on_output_chosen, tag='output_dialog',
                            width=860, height=540, modal=True, default_path=self.settings['output'])

    # Tools page

    def build_tools_page(self):
        t = self.t
        with dpg.group(tag='page_tools', show=False):
            self.heading('tools_title', 'tools_intro')
            for kind, title in (('ffmpeg', 'ffmpeg'), ('realesrgan', 'Real-ESRGAN')):
                with self.card():
                    with dpg.group(horizontal=True):
                        self.section(title)
                        self.chip('', tag=f'{kind}_state')
                    dpg.add_text(t(f'{kind}_what'), color=TEXT_DIM, wrap=820)
                    with dpg.group(horizontal=True):
                        dpg.add_button(label=t('download'), tag=f'download_{kind}', width=210,
                                       callback=lambda s, a, u: self.download(u), user_data=kind)
                        self.font(dpg.add_text('', tag=f'{kind}_path', color=TEXT_DIM), 'small')
                dpg.add_spacer(height=2)
            with dpg.group(horizontal=True):
                self.bar('download_bar', width=-130)
                self.theme(dpg.add_button(label=t('cancel'), tag='download_cancel', show=False, width=120,
                                          callback=lambda: self.cancel.set()), 'danger')
            with self.card():
                self.section(t('tools_folder'))
                with dpg.group(horizontal=True):
                    dpg.add_input_text(default_value=str(tools.tools_dir(self.settings)), readonly=True, width=-110)
                    self.quiet(t('open'), lambda: tools.open_folder(tools.tools_dir(self.settings)), width=100)
                dpg.add_spacer(height=4)
                self.section(t('language'))
                with dpg.group(horizontal=True):
                    dpg.add_combo(list(LANGUAGES.values()), default_value=LANGUAGES[self.t.language], width=280,
                                  callback=self.on_language)
                    self.label(t('language_note'))

    def refresh_tools(self):
        t = self.t
        ffmpeg, _ = tools.find_ffmpeg(self.settings)
        realesrgan = tools.find_realesrgan(self.settings)
        x264 = ffmpeg is not None and tools.ffmpeg_has_x264(ffmpeg)
        self.ready = ffmpeg is not None and realesrgan is not None and x264
        states = {
            'ffmpeg': (ffmpeg, x264, t('found') if ffmpeg and x264 else (t('no_x264') if ffmpeg else t('missing'))),
            'realesrgan': (realesrgan, realesrgan is not None,
                           t('found') + ' · ' + t('models', len(tools.models_of(realesrgan)))
                           if realesrgan else t('missing')),
        }
        for kind, (path, good, state) in states.items():
            kind_chip = 'chip_good' if good else ('chip_warn' if path else 'chip_bad')
            self.set_chip(f'{kind}_state', state, kind_chip)
            name = 'ffmpeg' if kind == 'ffmpeg' else 'Real-ESRGAN'
            self.set_chip(f'sidebar_{kind}', f'{name}: {state.split(" · ")[0]}' if good else f'{name}: {t("missing")}'
                          if not path else f'{name}: !', kind_chip)
            dpg.set_value(f'{kind}_path', shorten(str(path), 70) if path else '')
            if not tools.can_download(kind):
                dpg.configure_item(f'download_{kind}', show=False)
                if not good:
                    dpg.set_value(f'{kind}_path', t('no_download'))
            else:
                dpg.configure_item(f'download_{kind}', label=t('download_again') if good else t('download'))
                self.theme(f'download_{kind}', 'quiet' if good else 'nav_on')
                if not good:
                    dpg.bind_item_theme(f'download_{kind}', 0)

    def download(self, kind):
        t = self.t
        title = 'ffmpeg' if kind == 'ffmpeg' else 'Real-ESRGAN'
        dpg.configure_item('download_bar', show=True)
        dpg.set_value('download_bar', 0.0)
        self.message(t('downloading', title))

        def progress(done, total):
            def show():
                dpg.set_value('download_bar', done / total if total else 0.0)
                dpg.configure_item('download_bar', overlay=f'{done / 1048576:.0f} / {total / 1048576:.0f} MiB'
                                   if total else f'{done / 1048576:.0f} MiB')
            self.post(show)

        def work():
            tools.download(kind, self.settings, progress, self.cancel)
            self.save()
            self.post(lambda: self.message(t('downloaded', title), 'good'))

        self.start('download', work)

    def on_language(self, sender, value):
        for code, name in LANGUAGES.items():
            if name == value:
                self.settings['language'] = code
        self.save()

    # Disc page

    def build_disc_page(self):
        t = self.t
        with dpg.group(tag='page_disc', show=False):
            self.heading('disc_title', 'disc_intro')
            with self.card():
                with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp) as paths:
                    dpg.add_table_column(init_width_or_weight=1.0)
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=260)
                    with dpg.table_row():
                        with dpg.group():
                            self.label(t('iso'))
                            with dpg.group(horizontal=True, horizontal_spacing=12):
                                self.font(dpg.add_text('', tag='iso_name', color=TEXT), 'section')
                                self.font(dpg.add_text('', tag='iso_path', color=TEXT_DIM), 'small')
                        dpg.add_button(label=t('choose_iso'), tag='choose_iso', width=-1, height=40,
                                       callback=lambda: dpg.show_item('iso_dialog'))
                    with dpg.table_row():
                        with dpg.group():
                            self.label(t('output'))
                            self.font(dpg.add_text('', tag='output_path', color=TEXT), 'small')
                        with dpg.group(horizontal=True):
                            self.quiet(t('choose_folder'), lambda: dpg.show_item('output_dialog'), width=140)
                            self.quiet(t('open'), lambda: tools.open_folder(self.settings['output']), width=110)
                self.theme(paths, 'tight')
                dpg.add_spacer(height=4)
                with dpg.group(horizontal=True, tag='disc_chips'):
                    self.chip('', tag='chip_game')
                    self.chip('', tag='chip_count')
                    self.chip('', tag='chip_length')
                    self.chip('', tag='chip_done', kind='chip_good')
            with self.card(height=-96):
                with dpg.table(tag='disc_table', header_row=True, row_background=True, borders_innerH=True,
                               scrollY=True, height=-1, policy=dpg.mvTable_SizingStretchProp):
                    dpg.add_table_column(label='', width_fixed=True, init_width_or_weight=34)
                    dpg.add_table_column(label='', width_fixed=True, init_width_or_weight=THUMB_SIZE[0] + 8)
                    dpg.add_table_column(label=t('col_movie'), init_width_or_weight=3.0)
                    dpg.add_table_column(label=t('col_length'), init_width_or_weight=1.0)
                    dpg.add_table_column(label=t('col_size'), init_width_or_weight=1.0)
                    dpg.add_table_column(label=t('col_audio'), init_width_or_weight=0.8)
                    dpg.add_table_column(label=t('col_status'), init_width_or_weight=1.2)
            self.font(dpg.add_text(t('click_to_view'), color=TEXT_DIM), 'small')
            with dpg.group(horizontal=True):
                self.quiet(t('select_all'), lambda: self.check_all(self.disc_checks, True))
                self.quiet(t('select_none'), lambda: self.check_all(self.disc_checks, False))
                dpg.add_button(label=t('extract'), tag='extract', width=250, callback=self.extract)
                self.theme(dpg.add_button(label=t('cancel'), tag='disc_cancel', show=False, width=120,
                                          callback=lambda: self.cancel.set()), 'danger')
                self.bar('disc_bar')
        self.update_disc_chips()

    def show_paths(self):
        iso = self.settings.get('iso', '')
        dpg.set_value('iso_name', Path(iso).stem if iso else '-')
        dpg.set_value('iso_path', shorten(str(Path(iso).parent), 60) if iso else '')
        dpg.set_value('output_path', shorten(self.settings['output'], 90))

    def update_disc_chips(self):
        t = self.t
        self.show_paths()
        show = bool(self.movies)
        for tag in ('chip_game', 'chip_count', 'chip_length', 'chip_done'):
            dpg.configure_item(tag, show=show)
        if not show:
            return
        done = self.extracted_names()
        total = sum(m.seconds for m in self.movies)
        dpg.configure_item('chip_game', label=self.game)
        dpg.configure_item('chip_count', label=t('chip_movies', len(self.movies)))
        dpg.configure_item('chip_length', label=t('chip_length', duration_text(t, total)))
        count = sum(1 for m in self.movies if m.name in done)
        dpg.configure_item('chip_done', label=t('chip_extracted', count), show=count > 0)

    def on_iso_chosen(self, sender, data):
        path = data.get('file_path_name') or ''
        if path:
            self.load_iso(path)

    def on_output_chosen(self, sender, data):
        path = data.get('file_path_name') or ''
        if path:
            self.settings['output'] = path
            self.show_paths()
            self.save()
            self.fill_disc_table()
            self.refresh_extracted()

    def load_iso(self, path):
        try:
            with Iso(path) as iso:
                self.movies = list_movies(iso)
                self.game = iso.game_id() or Path(path).stem
        except (OSError, ValueError) as error:
            self.message(self.t('error', error), 'bad')
            return
        self.settings['iso'] = path
        self.save()
        self.show_paths()
        self.fill_disc_table()
        self.message('')

    def extracted_names(self):
        out = Path(self.settings['output'])
        return {p.stem for p in out.glob('*.json')} if out.is_dir() else set()

    def fill_disc_table(self):
        dpg.delete_item('disc_table', children_only=True, slot=1)
        done = self.extracted_names()
        previous = {m: dpg.get_value(c) for m, c in self.disc_checks.items() if dpg.does_item_exist(c)}
        self.disc_checks = {}
        for movie in self.movies:
            with dpg.table_row(parent='disc_table'):
                self.disc_checks[movie.name] = dpg.add_checkbox(
                    default_value=previous.get(movie.name, movie.name not in done and 'ICON' not in movie.name))
                self.thumb_button('disc', movie.name)
                dpg.add_text(movie.name)
                dpg.add_text(clock(movie.seconds), color=TEXT_DIM)
                dpg.add_text(f'{movie.size / 1048576:.1f} MiB', color=TEXT_DIM)
                dpg.add_text(str(movie.audio_tracks), color=TEXT_DIM)
                if movie.name in done:
                    self.chip(self.t('extracted'), 'chip_good')
                else:
                    dpg.add_text('')
        self.update_disc_chips()
        self.make_thumbs()

    @staticmethod
    def check_all(checks, value):
        for check in checks.values():
            if dpg.does_item_exist(check):
                dpg.set_value(check, value)

    def extract(self):
        t = self.t
        if not self.settings.get('iso') or not self.movies:
            self.message(t('pick_iso_first'), 'bad')
            return
        chosen = [m for m in self.movies if dpg.get_value(self.disc_checks.get(m.name, 0) or 0)]
        if not chosen:
            self.message(t('nothing_selected'), 'bad')
            return
        ffmpeg = tools.find_ffmpeg(self.settings)[0]
        if ffmpeg is None:
            self.message(t('no_ffmpeg_mp4'), 'warn')
        out = Path(self.settings['output'])
        dpg.configure_item('disc_bar', show=True)

        def work():
            with Iso(self.settings['iso']) as iso:
                for index, movie in enumerate(chosen):
                    if self.cancel.is_set():
                        raise tools.Cancelled()
                    self.post(lambda i=index, m=movie: (
                        dpg.set_value('disc_bar', i / len(chosen)),
                        dpg.configure_item('disc_bar', overlay=f'{i}/{len(chosen)}'),
                        self.message(t('extracting', m.name, i + 1, len(chosen)))))
                    extract_movie(iso, movie, out, ffmpeg)
            self.post(lambda: (self.fill_disc_table(), self.message(t('extracted_n', len(chosen)), 'good')))

        self.start('extract', work)

    # Upscale page

    def build_upscale_page(self):
        t = self.t
        with dpg.group(tag='page_upscale', show=False):
            self.heading('up_title', 'up_intro')
            with self.card():
                with dpg.group(horizontal=True, horizontal_spacing=18):
                    with dpg.group():
                        self.label(t('model'))
                        labels = [t(f'model_{m}') for m in MODELS]
                        current = self.settings.get('model', MODELS[0])
                        dpg.add_combo(labels, tag='model', width=420,
                                      default_value=t(f'model_{current}') if current in MODELS else labels[0],
                                      callback=self.on_upscale_settings)
                    with dpg.group():
                        self.label(t('resolution'))
                        labels = [t(f'res_{h}') for h in HEIGHTS]
                        height = self.settings.get('height', 1088)
                        dpg.add_combo(labels, tag='height', width=220,
                                      default_value=t(f'res_{height}') if height in HEIGHTS else labels[0],
                                      callback=self.on_upscale_settings)
                    with dpg.group():
                        self.label(t('quality'))
                        dpg.add_slider_int(tag='crf', min_value=10, max_value=24, width=180,
                                           default_value=int(self.settings.get('crf', 14)),
                                           callback=self.on_upscale_settings)
            with self.card(height=-150):
                with dpg.table(tag='up_table', header_row=True, row_background=True, borders_innerH=True,
                               scrollY=True, height=-1, policy=dpg.mvTable_SizingStretchProp):
                    dpg.add_table_column(label='', width_fixed=True, init_width_or_weight=34)
                    dpg.add_table_column(label='', width_fixed=True, init_width_or_weight=THUMB_SIZE[0] + 8)
                    dpg.add_table_column(label=t('col_movie'), init_width_or_weight=3.0)
                    dpg.add_table_column(label=t('col_length'), init_width_or_weight=1.0)
                    dpg.add_table_column(label=t('col_frames'), init_width_or_weight=1.0)
                    dpg.add_table_column(label=t('col_status'), init_width_or_weight=1.6)
            with dpg.group(horizontal=True):
                self.quiet(t('select_all'), lambda: self.check_all(self.upscale_checks, True))
                self.quiet(t('select_none'), lambda: self.check_all(self.upscale_checks, False))
                self.quiet(t('refresh'), self.refresh_extracted)
                self.quiet(t('open_remaster'), lambda: tools.open_folder(self.remaster_dir()))
                self.quiet(t('preview'), self.open_preview, tag='preview')
                dpg.add_button(label=t('upscale'), tag='upscale', width=260, callback=self.upscale)
                self.theme(dpg.add_button(label=t('cancel'), tag='up_cancel', show=False, width=120,
                                          callback=lambda: self.cancel.set()), 'danger')
            with dpg.group(horizontal=True):
                self.font(dpg.add_text('', tag='up_queue', color=ACCENT_BRIGHT), 'small')
                self.bar('up_bar', height=8)
            self.bar('up_movie_bar')

    def remaster_dir(self):
        return Path(self.settings['output']) / 'remaster'

    def on_upscale_settings(self, *_):
        t = self.t
        model = dpg.get_value('model')
        self.settings['model'] = next((m for m in MODELS if t(f'model_{m}') == model), MODELS[0])
        height = dpg.get_value('height')
        self.settings['height'] = next((h for h in HEIGHTS if t(f'res_{h}') == height), 1088)
        self.settings['crf'] = int(dpg.get_value('crf'))
        self.save()

    def refresh_extracted(self):
        if not dpg.does_item_exist('up_table'):
            return
        out = Path(self.settings['output'])
        self.extracted = []
        if out.is_dir():
            for meta_file in sorted(out.glob('*.json')):
                mp4 = meta_file.with_suffix('.mp4')
                if not mp4.is_file():
                    continue
                try:
                    meta = json.loads(meta_file.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                self.extracted.append((meta_file.stem, mp4, meta))
        previous = {m: dpg.get_value(c) for m, c in self.upscale_checks.items() if dpg.does_item_exist(c)}
        dpg.delete_item('up_table', children_only=True, slot=1)
        self.upscale_checks = {}
        for name, mp4, meta in self.extracted:
            status, kind = self.upscale_status(name, meta)
            with dpg.table_row(parent='up_table'):
                self.upscale_checks[name] = dpg.add_checkbox(default_value=previous.get(name, False))
                self.thumb_button('upscale', name)
                dpg.add_text(name)
                dpg.add_text(clock(meta.get('duration_seconds', 0)), color=TEXT_DIM)
                dpg.add_text(str(meta.get('frames', '?')), color=TEXT_DIM)
                if kind:
                    self.chip(status, kind)
                else:
                    dpg.add_text(status, color=TEXT_DIM)
        if not self.extracted and self.page == 'upscale':
            self.message(self.t('no_extracted'), 'warn')
        self.make_thumbs()

    def upscale_status(self, name, meta):
        t = self.t
        done = self.remaster_dir() / f'{name}.mp4'
        parts = self.remaster_dir() / f'{name}.parts'
        if done.is_file():
            return t('done'), 'chip_good'
        if parts.is_dir():
            made = len([p for p in parts.glob('part_*.mp4') if not p.name.endswith('.tmp.mp4')])
            frames = max(int(meta.get('frames', 1)), 1)
            return t('partial', min(99, made * 300 * 100 // frames)), 'chip_warn'
        return t('pending'), ''

    def selected_extracted(self):
        return [(n, mp4, meta) for n, mp4, meta in self.extracted
                if dpg.does_item_exist(self.upscale_checks.get(n, 0) or 0) and dpg.get_value(self.upscale_checks[n])]

    def tool_paths(self):
        ffmpeg, ffprobe = tools.find_ffmpeg(self.settings)
        realesrgan = tools.find_realesrgan(self.settings)
        if ffmpeg is None or realesrgan is None or not tools.ffmpeg_has_x264(ffmpeg):
            self.message(self.t('need_tools'), 'bad')
            return None
        return ffmpeg, ffprobe, realesrgan

    def upscale(self):
        t = self.t
        paths = self.tool_paths()
        if paths is None:
            return
        chosen = self.selected_extracted()
        if not chosen:
            self.message(t('nothing_selected'), 'bad')
            return
        ffmpeg, ffprobe, realesrgan = paths
        model, height, crf = self.settings['model'], int(self.settings['height']), int(self.settings['crf'])
        dpg.configure_item('up_movie_bar', show=True)
        dpg.configure_item('up_bar', show=len(chosen) > 1)

        def work():
            for index, (name, mp4, meta) in enumerate(chosen):
                self.post(lambda i=index: (dpg.set_value('up_queue', t('upscaling_queue', i + 1, len(chosen))),
                                           dpg.set_value('up_bar', i / len(chosen))))

                def progress(p, i=index):
                    def show():
                        fraction = p.frames_done / max(p.frames, 1)
                        dpg.set_value('up_movie_bar', fraction)
                        dpg.configure_item('up_movie_bar', overlay=f'{p.movie}  ·  {fraction * 100:.0f}%')
                        dpg.set_value('up_bar', (i + fraction) / len(chosen))
                        left = duration_text(t, p.seconds_left) if p.fps else '…'
                        self.message(t('upscaling', p.movie, p.frames_done, p.frames, p.fps, left))
                    self.post(show)

                upscale_movie(mp4, self.remaster_dir() / f'{name}.mp4', ffmpeg, ffprobe, realesrgan, model, height,
                              crf, progress=progress, cancel=self.cancel)
                self.post(self.refresh_extracted)
            self.post(lambda: (self.message(t('upscaled_n', len(chosen)), 'good'), dpg.set_value('up_queue', '')))

        self.start('upscale', work)

    # Thumbnails and the movie viewer

    def thumb_button(self, where, name):
        if self.blank_thumb is None:
            width, height = THUMB_SIZE
            with dpg.texture_registry():
                self.blank_thumb = dpg.add_static_texture(width, height, [FIELD[0] / 255, FIELD[1] / 255,
                                                                          FIELD[2] / 255, 1.0] * (width * height))
        texture = self.thumb_textures.get((where, name), self.blank_thumb)
        button = dpg.add_image_button(texture, width=THUMB_SIZE[0], height=THUMB_SIZE[1],
                                      callback=lambda s, a, u: self.open_viewer(*u), user_data=(where, name))
        self.theme(button, 'thumb')
        self.thumb_buttons[(where, name)] = button
        return button

    def make_thumbs(self):
        """Fills the thumbnails both lists still lack, on a thread of their own:
        from the cache at once, else one by one with ffmpeg."""
        ffmpeg = tools.find_ffmpeg(self.settings)[0]
        if ffmpeg is None:
            return
        self.thumb_generation += 1
        generation = self.thumb_generation
        iso_path = self.settings.get('iso', '')
        jobs = []
        for movie in self.movies:
            if ('disc', movie.name) not in self.thumb_textures:
                frame = int(movie.seconds * FPS * 0.25)
                jobs.append(('disc', movie.name, frame, None, movie, f'{iso_path}|{movie.path}'))
        for name, mp4, meta in self.extracted:
            if ('upscale', name) not in self.thumb_textures:
                jobs.append(('upscale', name, int(meta.get('frames', 4) * 0.25), mp4, None, None))
        if not jobs:
            return
        t = self.t

        def work():
            iso = None
            try:
                for index, (where, name, frame, path, movie, key) in enumerate(jobs):
                    if generation != self.thumb_generation:
                        return
                    pixels = cached(key, frame, THUMB_SIZE) if key else None
                    try:
                        if pixels is None and movie is not None:
                            if iso is None:
                                iso = Iso(iso_path)
                            data, _ = video_bytes(iso, movie)
                            pixels = frame_rgba(ffmpeg, frame, THUMB_SIZE, data=data, key=key)
                        elif pixels is None:
                            pixels = frame_rgba(ffmpeg, frame, THUMB_SIZE, path=path)
                    except (OSError, RuntimeError):
                        continue
                    values = as_floats(pixels)
                    self.post(lambda w=where, n=name, v=values, i=index: self.set_thumb(w, n, v, i, len(jobs)))
            finally:
                if iso is not None:
                    iso.close()
                self.post(lambda: dpg.set_value('thumb_status', '') if dpg.does_item_exist('thumb_status') else None)

        threading.Thread(target=work, daemon=True).start()

    def set_thumb(self, where, name, values, index, count):
        width, height = THUMB_SIZE
        if (where, name) not in self.thumb_textures:
            with dpg.texture_registry():
                self.thumb_textures[(where, name)] = dpg.add_static_texture(width, height, values)
        button = self.thumb_buttons.get((where, name))
        if button is not None and dpg.does_item_exist(button):
            dpg.configure_item(button, texture_tag=self.thumb_textures[(where, name)])
        if dpg.does_item_exist('thumb_status'):
            dpg.set_value('thumb_status', self.t('thumbs_progress', index + 1, count) if index + 1 < count else '')

    def open_viewer(self, where, name):
        """Four frames of a movie, larger, and buttons to watch it."""
        t = self.t
        ffmpeg = tools.find_ffmpeg(self.settings)[0]
        if ffmpeg is None:
            self.message(t('need_tools'), 'bad')
            return
        out = Path(self.settings['output'])
        mp4 = out / f'{name}.mp4'
        remaster = self.remaster_dir() / f'{name}.mp4'
        movie = next((m for m in self.movies if m.name == name), None)
        meta = next((m for n, _, m in self.extracted if n == name), {})
        seconds = movie.seconds if movie else meta.get('duration_seconds', 0)
        frames = int(meta.get('frames') or seconds * FPS)
        tracks = movie.audio_tracks if movie else meta.get('audio_streams', 0)
        width, height = VIEW_SIZE
        if self.view_textures is None:
            blank = [CARD[0] / 255, CARD[1] / 255, CARD[2] / 255, 1.0] * (width * height)
            with dpg.texture_registry():
                self.view_textures = [dpg.add_dynamic_texture(width, height, blank) for _ in VIEW_AT]
        blank = [CARD[0] / 255, CARD[1] / 255, CARD[2] / 255, 1.0] * (width * height)
        for texture in self.view_textures:
            dpg.set_value(texture, blank)
        if dpg.does_item_exist('viewer'):
            dpg.delete_item('viewer')
        with dpg.window(label=name, tag='viewer', modal=True, no_resize=True, no_scrollbar=True,
                        width=width * 2 + 66, height=height * 2 + 230,
                        pos=centred(width * 2 + 66, height * 2 + 230)):
            self.font(dpg.add_text(t('view_info', clock(seconds), frames, tracks), color=TEXT_DIM), 'small')
            for row in range(2):
                with dpg.group(horizontal=True, horizontal_spacing=10):
                    for column in range(2):
                        index = row * 2 + column
                        with dpg.group():
                            dpg.add_image(self.view_textures[index])
                            self.font(dpg.add_text(clock(seconds * VIEW_AT[index]), color=TEXT_DIM), 'small')
            with dpg.group(horizontal=True):
                if mp4.is_file():
                    dpg.add_button(label=t('open_player'), width=230, callback=lambda: tools.open_file(mp4))
                else:
                    self.font(dpg.add_text(t('extract_to_watch'), color=TEXT_DIM), 'small')
                if remaster.is_file():
                    self.theme(dpg.add_button(label=t('open_remaster_player'), width=260,
                                              callback=lambda: tools.open_file(remaster)), 'quiet')
            self.font(dpg.add_text(t('loading_frames'), tag='viewer_status', color=TEXT_DIM), 'small')
        self.theme('viewer', 'preview')
        iso_path = self.settings.get('iso', '')

        def work():
            data = None
            if not mp4.is_file() and movie is not None:
                with Iso(iso_path) as iso:
                    data, _ = video_bytes(iso, movie)
            for index, at in enumerate(VIEW_AT):
                frame = int(frames * at)
                try:
                    pixels = frame_rgba(ffmpeg, frame, VIEW_SIZE, path=mp4 if data is None else None, data=data,
                                        key=None if data is None else f'{iso_path}|{movie.path}')
                except (OSError, RuntimeError):
                    continue
                values = as_floats(pixels)
                self.post(lambda i=index, v=values: dpg.set_value(self.view_textures[i], v))
            self.post(lambda: dpg.set_value('viewer_status', '') if dpg.does_item_exist('viewer_status') else None)

        threading.Thread(target=work, daemon=True).start()

    # Preview

    def open_preview(self):
        t = self.t
        chosen = self.selected_extracted()
        if len(chosen) != 1:
            self.message(t('pick_one'), 'warn')
            return
        if self.tool_paths() is None:
            return
        name, mp4, meta = chosen[0]
        self.preview_movie = (name, mp4, meta)
        width, height = PREVIEW_SIZE
        if self.preview_textures is None:
            blank = [CARD[0] / 255, CARD[1] / 255, CARD[2] / 255, 1.0] * (width * height)
            with dpg.texture_registry():
                self.preview_textures = (dpg.add_dynamic_texture(width, height, blank),
                                         dpg.add_dynamic_texture(width, height, blank))
        if dpg.does_item_exist('preview_window'):
            dpg.delete_item('preview_window')
        model = self.settings['model']
        with dpg.window(label=t('preview_title', name), tag='preview_window', modal=True, no_resize=True,
                        no_scrollbar=True, width=width * 2 + 72, height=height + 170,
                        pos=centred(width * 2 + 72, height + 170)):
            with dpg.group(horizontal=True):
                self.label(t('frame'))
                dpg.add_slider_int(tag='preview_frame', min_value=0, max_value=max(int(meta.get('frames', 1)) - 1, 0),
                                   default_value=int(meta.get('frames', 1)) // 3, width=width + 120)
                dpg.add_button(label=t('update'), tag='preview_update', width=150, callback=self.run_preview)
            with dpg.group(horizontal=True, horizontal_spacing=14):
                with dpg.group():
                    self.chip(t('original'), 'chip_warn')
                    dpg.add_image(self.preview_textures[0])
                with dpg.group():
                    self.chip(t('remaster', model), 'chip_good')
                    dpg.add_image(self.preview_textures[1])
            self.font(dpg.add_text('', tag='preview_status', color=TEXT_DIM), 'small')
        self.theme('preview_window', 'preview')
        self.run_preview()

    def run_preview(self):
        t = self.t
        paths = self.tool_paths()
        if paths is None or self.preview_movie is None:
            return
        ffmpeg, ffprobe, realesrgan = paths
        name, mp4, meta = self.preview_movie
        frame = dpg.get_value('preview_frame')
        width, height = PREVIEW_SIZE
        dpg.set_value('preview_status', t('previewing'))
        model, out_height = self.settings['model'], int(self.settings['height'])

        def work():
            original, upscaled, w, h = preview(mp4, frame, ffmpeg, ffprobe, realesrgan, model, out_height,
                                               width, height, cancel=self.cancel)
            data = [_floats(original, w, h, width, height), _floats(upscaled, w, h, width, height)]

            def show():
                for texture, values in zip(self.preview_textures, data):
                    dpg.set_value(texture, values)
                if dpg.does_item_exist('preview_status'):
                    dpg.set_value('preview_status', '')
            self.post(show)

        self.start('preview', work)

    def build_about_page(self):
        with dpg.group(tag='page_about', show=False):
            self.font(dpg.add_text(self.t('about_title'), color=TEXT), 'title')
            with self.card():
                dpg.add_text(self.t('about_text'), wrap=840, color=TEXT_DIM)

    # -- run -----------------------------------------------------------------

    def run(self):
        dpg.create_context()
        self.build_fonts()
        self.build_theme()
        self.build()
        dpg.create_viewport(title=self.t('app'), width=1240, height=920, min_width=1000, min_height=680,
                            clear_color=BACKGROUND)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window('main', True)
        # KMT_SCREENSHOT=file.png [KMT_PAGE=disc] [KMT_PREVIEW=MOVIE]:
        # save the window once idle and close, to check the look without
        # anyone at the screen.
        screenshot = os.environ.get('KMT_SCREENSHOT')
        if os.environ.get('KMT_PAGE') in PAGES:
            self.show_page(os.environ['KMT_PAGE'])
        if os.environ.get('KMT_VIEW'):
            where, name = os.environ['KMT_VIEW'].split(':')
            self.show_page('disc' if where == 'disc' else 'upscale')
            self.open_viewer(where, name)
        if os.environ.get('KMT_PREVIEW'):
            self.show_page('upscale')
            dpg.set_value(self.upscale_checks[os.environ['KMT_PREVIEW']], True)
            self.open_preview()
        frames = 0
        shot_at = None
        while dpg.is_dearpygui_running():
            frames += 1
            if (screenshot and shot_at is None and frames >= 90 and self.busy is None
                    and not dpg.get_value('thumb_status') and frames >= int(os.environ.get('KMT_WAIT', '90'))):
                shot_at = frames + 20
            if screenshot and frames == shot_at:
                dpg.output_frame_buffer(file=screenshot)
            if screenshot and shot_at is not None and frames == shot_at + 30:
                break
            for _ in range(200):
                try:
                    self.events.get_nowait()()
                except queue.Empty:
                    break
            dpg.render_dearpygui_frame()
        self.cancel.set()
        time.sleep(0.2)
        dpg.destroy_context()


def _floats(rgba, w, h, width, height):
    """RGBA bytes of a w x h image as the float list a width x height texture
    takes, centred on the card's colour when smaller."""
    if (w, h) == (width, height):
        return [b / 255.0 for b in rgba]
    out = [CARD[0] / 255, CARD[1] / 255, CARD[2] / 255, 1.0] * (width * height)
    left, top = (width - w) // 2, (height - h) // 2
    for row in range(h):
        start = ((top + row) * width + left) * 4
        out[start:start + w * 4] = [b / 255.0 for b in rgba[row * w * 4:(row + 1) * w * 4]]
    return out


def main():
    App().run()


if __name__ == '__main__':
    main()
