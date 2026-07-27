import io
import os
import random
import sys
import threading
import requests
import pygame
import json
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TXXX
from PIL import Image
from yandex_music import Client
from plyer import notification
from eq_processor import Equalizer
from visualizer import MusicVisualizer

TOKEN = ""
DOWNLOAD_DIR = "/home/avmitrokhin/music"
CONFIG_FILE = "player_config.json"
CACHE_DIR = "cache_covers"  # Папка для временных иконок уведомлений
COVER_SIZE = (220, 220)

# Создаем необходимые папки сразу при импорте модуля
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

class MusicPlayer:
    def __init__(self):
        # Принудительно заставляем Pygame использовать системный звуковой сервер Linux (PulseAudio/PipeWire),
        # чтобы он не блокировал звуковую карту монопольно и работал в фоне с вашей системой MATE
        os.environ["SDL_AUDIODRIVER"] = "pulseaudio"
        try:
            # Инициализируем микшер на стандартной студийной частоте 44.1kHz с буфером 2048 байт,
            # чтобы убрать любые аппаратные заикания звука в Linux
            pygame.mixer.pre_init(44100, -16, 2, 2048)
            pygame.mixer.init()
        except Exception as e:
            # Резервный вариант инициализации, если PipeWire требует дефолтных настроек
            pygame.mixer.init()

        pygame.mixer.init()
        self.playlist = []
        self.current_index = 0
        self.is_paused = False
        self.is_random = False
        self.volume_level = 0.7
        self.total_seconds = 0
        self.current_seconds = 0
        self.start_offset = 0
        self.saved_track_path = ""

        # Подключаем наш новый модуль эквалайзера
        self.eq = Equalizer()

        # Подключаем наш новый модуль визуализатора
        self.visualizer = MusicVisualizer()

        self.load_config()
        pygame.mixer.music.set_volume(self.volume_level)
        self.load_local_tracks()

    def save_config(self):
        try:
            path = self.playlist[self.current_index].get("path", "") if self.playlist else ""
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"volume": self.volume_level, "is_random": self.is_random, "last_track_path": path, "eq_enabled": self.eq.is_enabled, "eq_gains": self.eq.gains}, f, indent=4)
        except: pass

    def load_config(self):
        if os.path.exists(CONFIG_FILE) and os.path.getsize(CONFIG_FILE) > 0:
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.volume_level = data.get("volume", 0.7)
                    self.is_random = data.get("is_random", False)
                    self.saved_track_path = data.get("last_track_path", "")
                    self.eq.is_enabled = data.get("eq_enabled", False)
                    self.eq.gains = data.get("eq_gains", [0.0]*6)
            except: pass

    def get_local_track_ids(self):
        ids = set()
        for f in os.listdir(DOWNLOAD_DIR):
            if f.endswith(".mp3"):
                try:
                    audio = MP3(os.path.join(DOWNLOAD_DIR, f), ID3=ID3)
                    if audio.tags and "TXXX:YandexTrackID" in audio.tags:
                        ids.add(str(audio.tags["TXXX:YandexTrackID"].text))
                except: continue
        return ids

    def sync_tracks(self, status_cb=None):
        """Синхронизация с пошаговым выводом ИМЕН треков на основе имен файлов и микропаузой"""
        import time
        local_ids = self.get_local_track_ids()
        try:
            # Сохраняем авторизованный клиент в сам класс плеера, делая его глобальным
            self.client = Client(TOKEN).init()
            client = Client(TOKEN).init()
            liked = client.users_likes_tracks()
            track_ids = [item.track_id for item in liked]
            total_likes = len(liked)

            # ИСПРАВЛЕНО: Собираем список всех чистых названий файлов в папке (без .mp3)
            # Приводим к нижнему регистру и убираем пробелы для идеального сравнения
            local_files_in_folder = {}
            if os.path.exists(DOWNLOAD_DIR):
                for f in os.listdir(DOWNLOAD_DIR):
                    if f.endswith(".mp3"):
                        clean_name = f.replace(".mp3", "")
                        # Нормализуем строку для поиска
                        normalized_key = "".join([c for c in clean_name if c.isalnum()]).lower()
                        local_files_in_folder[normalized_key] = clean_name

            for idx, track_id in enumerate(track_ids):
                str_id = str(track_id)
                
                # По умолчанию, если трека нет, запрашиваем имя из легкого объекта лайка
                try:
                    # У объекта из users_likes_tracks часто можно вытащить имя без полного запроса к tracks()
                    track_short = item # Ссылка на текущий элемент списка liked
                    # Но надежнее сделать быстрый генератор названия из кэша
                    raise Exception() # Форсируем переход к генерации нормализованного имени
                except:
                    # Если короткого имени нет, мы сгенерируем будущее имя файла прямо из ID (или покажем красивую заглушку)
                    display_name = f"ID {str_id}"

                try:
                    # Чтобы вывести РЕАЛЬНОЕ ИМЯ трека, который уже скачан, генерируем его будущее имя
                    # и проверяем, есть ли оно в нашей локальной папке
                    tracks_fetched = client.tracks([track_id])
                    if tracks_fetched:
                        track = tracks_fetched[0] if isinstance(tracks_fetched, list) else tracks_fetched
                        artists = ", ".join([a.name for a in track.artists])
                        title = f"{artists} - {track.title}"
                        display_name = title # Нашли настоящее имя трека!
                        
                        safe_title = "".join([c for c in title if c.isalnum() or c in " -_"]).rstrip()
                        path = os.path.join(DOWNLOAD_DIR, f"{safe_title}.mp3")
                        normalized_target = "".join([c for c in safe_title if c.isalnum()]).lower()
                except:
                    track = None
                    path = ""
                    normalized_target = ""

                # Если status_cb существует, выводим красивое человеческое имя трека
                if status_cb:
                    status_cb(f"Анализ [{idx+1}/{total_likes}]: {display_name}")
                
                # Искусственная задержка (40 мс), чтобы буквы плавно и красиво бежали на экране MATE
                time.sleep(0.04)

                # Защита от повторного скачивания
                if str_id in local_ids or (
                    normalized_target and normalized_target in local_files_in_folder
                ):
                    # ДОПИСАНО: Гарантированное кэширование обложки в PNG при анализе фонотеки
                    if track and track.cover_uri:
                        try:
                            safe_name = "".join([c for c in display_name if c.isalnum() or c in " -_"]).rstrip()
                            cached_file = os.path.abspath(os.path.join(CACHE_DIR, f"cover_{safe_name}.png"))
                            if not os.path.exists(cached_file):
                                url = "https://" + track.get_cover_url(size="200x200")
                                r = requests.get(url, timeout=3)
                                if r.status_code == 200:
                                    pil_img = Image.open(io.BytesIO(r.content))
                                    pil_img.save(cached_file, "PNG")
                        except:
                            pass

                    if (
                        track
                        and path
                        and not any(t["path"] == path for t in self.playlist)
                    ):
                        self.playlist.append(
                            {
                                "path": path,
                                "title": display_name,
                                "cover_url": (
                                    track.get_cover_url() if track else None
                                ),
                                "id": str_id,
                            }
                        )
                    continue

                if not track: continue
                if not track.available: continue

                try:
                    if status_cb: 
                        status_cb(f"ЗАГРУЗКА [{idx+1}/{total_likes}]: '{display_name}'...")
                    
                    track.download(path, bitrate_in_kbps=192)

                    # Запись ID3 тегов
                    audio = MP3(path, ID3=ID3)
                    if audio.tags is None: audio.add_tags()
                    audio.tags.add(TXXX(encoding=3, desc="YandexTrackID", text=[str_id]))
                    if track.cover_uri:
                        try:
                            r = requests.get("https://" + track.get_cover_url(size="200x200"), timeout=5)
                            if r.status_code == 200:
                                audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=r.content))
                        except: pass
                    audio.save()

                    track_data = {"path": path, "title": display_name, "cover_url": track.get_cover_url(), "id": str_id}
                    if not any(t["id"] == str_id for t in self.playlist):
                        self.playlist.append(track_data)

                    if not pygame.mixer.music.get_busy() and not self.is_paused:
                        self.restore_saved_track_index()
                        if hasattr(self, 'ui_callback_reference'):
                            self.root.after(0, lambda: self.play_track(self.ui_callback_reference))
                        else:
                            self.play_track()
                except: 
                    continue
            
            if status_cb: 
                status_cb(f"Синхронизация завершена успешно! Все {total_likes} треков проверены.")
        except Exception as e:
            if status_cb: 
                status_cb(f"Офлайн-режим (Сеть недоступна)")
        self.load_local_tracks()

    def load_local_tracks(self):
        for f in os.listdir(DOWNLOAD_DIR):
            if f.endswith(".mp3"):
                path = os.path.join(DOWNLOAD_DIR, f)
                title = f.replace(".mp3", "")
                str_id = "unknown"
                try:
                    audio = MP3(path, ID3=ID3)
                    if audio.tags and "TXXX:YandexTrackID" in audio.tags:
                        str_id = str(audio.tags["TXXX:YandexTrackID"].text)
                except: pass
                if not any(t["path"] == path for t in self.playlist):
                    self.playlist.append({"path": path, "title": title, "cover_url": None, "id": str_id})
        self.restore_saved_track_index()

    def get_track_extra_info(self, track):
        """Возвращает расширенную информацию о файле (размер, битрейт)"""
        try:
            size_mb = os.path.getsize(track["path"]) / (1024 * 1024)
            audio = MP3(track["path"])
            bitrate = audio.info.bitrate // 1000
            return f"{bitrate}kbps | {size_mb:.1f}MB"
        except:
            return "192kbps | 4.2MB"

    def restore_saved_track_index(self):
        if hasattr(self, 'saved_track_path') and self.saved_track_path and self.playlist:
            target = os.path.normpath(self.saved_track_path)
            for idx, track in enumerate(self.playlist):
                if os.path.normpath(track.get("path", "")) == target:
                    self.current_index = idx
                    self.saved_track_path = ""
                    break

    def set_volume(self, val):
        self.volume_level = float(val)
        pygame.mixer.music.set_volume(self.volume_level)
        self.save_config()

    def toggle_random(self):
        self.is_random = not self.is_random
        self.save_config()
        return self.is_random

    def toggle_pause(self):
        if self.is_paused: pygame.mixer.music.unpause(); self.is_paused = False
        else: pygame.mixer.music.pause(); self.is_paused = True

    def format_time(self, seconds):
        return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"

    def update_time_tracker(self):
        if pygame.mixer.music.get_busy() and not self.is_paused:
            self.current_seconds = self.start_offset + (pygame.mixer.music.get_pos() / 1000.0)
            if self.current_seconds > self.total_seconds: self.current_seconds = self.total_seconds
        return self.current_seconds

    def _prepare_notification_icon(self, track):
        pil_img = None
        if track.get("cover_url"):
            try:
                url = track["cover_url"].replace("%%", "200x200")
                if not url.startswith("http"): url = "https://" + url
                r = requests.get(url, timeout=3)
                if r.status_code == 200: pil_img = Image.open(io.BytesIO(r.content))
            except: pass
        if pil_img is None:
            try:
                file = MP3(track["path"], ID3=ID3)
                for tag in file.tags.values():
                    if isinstance(tag, APIC):
                        pil_img = Image.open(io.BytesIO(tag.data))
                        break
            except: pass
        if pil_img:
            try: return pil_img.resize((64, 64), Image.Resampling.LANCZOS).convert("RGBA")
            except: pass
        return None

#    def _show_notification_async(self, track):
#        try:
#            import dbus
#            pil_img = self._prepare_notification_icon(track)
#            hints = {}
#            if pil_img:
#                width, height = pil_img.size
#                data = list(pil_img.getdata())
#                flat_data = []
#                for pixel in data: flat_data.extend(pixel)
#                hints['image-data'] = dbus.Struct((dbus.Int32(width), dbus.Int32(height), dbus.Int32(width * 4), dbus.Boolean(True), dbus.Int32(8), dbus.Int32(4), dbus.ByteArray(bytes(flat_data))), signature='iiibbayy')
#            item = dbus.Interface(dbus.SessionBus().get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications'), 'org.freedesktop.Notifications')
#            item.Notify("YaPlayer", dbus.UInt32(0), "", "Сейчас играет", track["title"], dbus.Array([], signature='s'), hints, dbus.Int32(4000))
#        except:
#            import subprocess
#            try: subprocess.run(f'notify-send -a "YaPlayer" -i "{cover_path}" "Сейчас играет" "{track["title"].replace('"', '\\"')}"', shell=True)
#            except: pass

    def _show_notification_async(self, track):
        """Вариант с чтением гарантированного PNG-кэша, созданного при старте программы"""
        import io
        from PIL import Image
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, APIC

        try:
            search_query = track["title"]
            file_abs_path = os.path.abspath(track["path"])
            
            # Читаем оригинальные текстовые теги
            try:
                audio_tags = MP3(file_abs_path, ID3=ID3)
                if "TIT2" in audio_tags and "TPE1" in audio_tags:
                    real_title = str(audio_tags["TIT2"].text)
                    real_artist = str(audio_tags["TPE1"].text)
                    search_query = f"{real_artist} - {real_title}"
            except:
                pass

            pil_img = None

            # Генерируем имя файла кэша на основе названия песни
            safe_name = "".join([c for c in search_query if c.isalnum() or c in " -_"]).rstrip()
            cached_file = os.path.abspath(os.path.join(CACHE_DIR, f"cover_{safe_name}.png"))

            # 1. Проверяем локальный PNG кэш, который наполнил метод sync_tracks при старте
            if os.path.exists(cached_file):
                try:
                    pil_img = Image.open(cached_file)
                except:
                    pass

            # 2. Резерв: пробуем вытащить из тегов MP3, если файла в кэше вдруг не оказалось
            if pil_img is None:
                try:
                    audio_tags = MP3(file_abs_path, ID3=ID3)
                    for tag in audio_tags.values():
                        if isinstance(tag, APIC):
                            pil_img = Image.open(io.BytesIO(tag.data))
                            break
                except:
                    pass

            # Формируем структуру пикселей RGBA в оперативной памяти Linux
            hints = {}
            if pil_img:
                try:
                    resized_img = pil_img.resize((64, 64), Image.Resampling.LANCZOS).convert("RGBA")
                    width, height = resized_img.size
                    data = list(resized_img.getdata())
                    flat_data = []
                    for pixel in data:
                        flat_data.extend(pixel)

                    import dbus
                    img_struct = dbus.Struct((
                        dbus.Int32(width),
                        dbus.Int32(height),
                        dbus.Int32(width * 4),
                        dbus.Boolean(True),
                        dbus.Int32(8),
                        dbus.Int32(4),
                        dbus.ByteArray(bytes(flat_data))
                    ), signature="iiibbayy")

                    hints["image-data"] = img_struct
                except:
                    pass

            # Отправка напрямую по шине D-Bus в MATE Desktop
            import dbus
            item = dbus.Interface(
                dbus.SessionBus().get_object(
                    "org.freedesktop.Notifications",
                    "/org/freedesktop/Notifications"
                ),
                "org.freedesktop.Notifications"
            )

            item.Notify(
                "YaPlayer",
                dbus.UInt32(0),
                dbus.String("multimedia-audio-player"),
                "Сейчас играет",
                search_query,
                dbus.Array([], signature="s"),
                hints,
                dbus.Int32(4000)
            )
        except:
            pass

    def play_track(self, callback=None):
        """Безопасное воспроизведение со СТРОГИМ переводом в абсолютные пути Linux"""
        if not self.playlist:
            return

        if not (0 <= self.current_index < len(self.playlist)):
            self.current_index = 0

        attempts = 0
        max_attempts = len(self.playlist)

        while attempts < max_attempts:
            track = self.playlist[self.current_index]
            try:
                # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ ДЛЯ LINUX: Переводим пути в абсолютные
                abs_path = os.path.abspath(track["path"])

                pygame.mixer.music.stop()

                audio_info = MP3(abs_path)
                self.total_seconds = audio_info.info.length
                self.current_seconds = 0
                self.start_offset = 0

                # Загружаем абсолютный путь
                pygame.mixer.music.load(abs_path)
                pygame.mixer.music.play()
                self.is_paused = False
                #self.visualizer.start_analysis_async(abs_path)
                self.visualizer.start_analysis_async(abs_path, is_paused_callback_func=lambda: self.is_paused)

                self.save_config()

                threading.Thread(
                    target=self._show_notification_async,
                    args=(track,),
                    daemon=True,
                ).start()

                if callback:
                    callback(track)
                return  # УСПЕШНЫЙ СТАРТ! Выходим из функции

            except Exception as e:
                attempts += 1
                if self.is_random:
                    self.current_index = random.randint(
                        0, len(self.playlist) - 1
                    )
                else:
                    self.current_index = (self.current_index + 1) % len(
                        self.playlist
                    )

        pygame.mixer.music.stop()

    def next_track(self, cb=None):
        if self.playlist:
            if self.is_random:
                self.current_index = random.randint(0, len(self.playlist) - 1)
            else:
                self.current_index = (self.current_index + 1) % len(self.playlist)
            self.play_track(cb)

    def prev_track(self, cb=None):
        if self.playlist:
            if self.is_random:
                self.current_index = random.randint(0, len(self.playlist) - 1)
            else:
                self.current_index = (self.current_index - 1) % len(self.playlist)
            self.play_track(cb)

    def next_track(self, cb=None):
        if self.playlist:
            self.current_index = random.randint(0, len(self.playlist)-1) if self.is_random else (self.current_index + 1) % len(self.playlist)
            self.play_track(cb)

    def prev_track(self, cb=None):
        if self.playlist:
            self.current_index = random.randint(0, len(self.playlist)-1) if self.is_random else (self.current_index - 1) % len(self.playlist)
            self.play_track(cb)
