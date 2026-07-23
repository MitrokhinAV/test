import threading, pygame, time, sys, os

# --- НАСТРОЙКА ВИДА БЕГУНКА В ТЕРМИНАЛЕ ---
BAR_LENGTH = 40         # Длина полосы прогресса в символах
FILL_CHAR = "░"         # Чем заполнена пройденная дорожка
EMPTY_CHAR = "─"        # Чем заполнена оставшаяся дорожка
SLIDER_CHAR = ""       # Маркер-бегунок (Огонёк). Можно заменить на 🔥 '🔘', '▶', '█' и т.д.
# ------------------------------------------

# Глобальные переменные для хранения последнего статуса сети, чтобы плеер его не затирал
current_sync_status = "Ожидание сети..."
show_eq_panel = False  # Флаг отображения панели эквалайзера

def get_keypress_linux():
    """Считывает один символ из терминала Linux мгновенно, без ожидания Enter"""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
        # Обработка стрелок (они приходят как 3 символа: \x1b, [, и код)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "up"  # Стрелка вверх
                if ch3 == "B":
                    return "down"  # Стрелка вниз
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def draw_cli_timeline(player):
    """Фоновое обновление строк через жесткие ANSI-координаты"""
    global current_sync_status
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

    while True:
        # Проверяем, не пытается ли система закрыться
        if pygame.mixer.get_init() is None:
            break

        if player.playlist and player.total_seconds > 0:
            current = player.update_time_tracker()
            total = player.total_seconds
            remaining = total - current

            # Проверка автоперехода (если трек закончился сам)
            if current >= total - 0.5 and pygame.mixer.music.get_busy() == 0:
                player.next_track()
                time.sleep(0.5)
                continue

            # Сборка ползунка
            progress_ratio = current / total if total > 0 else 0
            filled_len = int(BAR_LENGTH * progress_ratio)
            bar = (
                FILL_CHAR * filled_len
                + SLIDER_CHAR
                + EMPTY_CHAR * (BAR_LENGTH - filled_len)
            )

            curr_str = player.format_time(current)
            rem_str = player.format_time(remaining)
            tot_str = player.format_time(total)
            current_volume = int(pygame.mixer.music.get_volume() * 100)

            track = player.playlist[player.current_index]
            extra_info = player.get_track_extra_info(track)

            # СТРОКА 1: Техническая информация (Таймлайн, Громкость, Качество)
            player_line = (
                f"[{curr_str} {bar} -{rem_str}/{tot_str}] 🔊 {current_volume}%"
            )
            if player.is_paused:
                player_line += " 💤 ПАУЗА"
            if player.is_random:
                player_line += " 🎲 РАНДОМ"

            sys.stdout.write(f"\033[1;1H\033[K{player_line}\n")

            # СТРОКА 2: НАЗВАНИЕ ТРЕКА ВЫНЕСЕНО НА ОТДЕЛЬНУЮ СТРОКУ
            sys.stdout.write(
                f"\033[2;1H\033[K🎵 Трек: \033[1;32m{track['title']}\033[0m ({extra_info})\n"
            )

            # СТРОКА 3: Живая, динамическая синхронизация (больше не зависает!)
            sys.stdout.write(
                f"\033[3;1H\033[K🌐 Сеть: {current_sync_status}\n"
            )

            # СТРОКА 4: Компактный эквалайзер
            if player.eq.is_enabled:
                short_labels = ["60", "150", "400", "1k", "3k", "15k"]
                eq_bands_str = " ".join(
                    [
                        f"[{i+1}]{short_labels[i]}:{gain:+.1f}dB"
                        for i, gain in enumerate(player.eq.gains)
                    ]
                )
                sys.stdout.write(f"\033[4;1H\033[K💫 EQ (ВКЛ) | {eq_bands_str}\n")
            else:
                sys.stdout.write(f"\033[4;1H\033[K💫 EQ (ВЫКЛ)\n")

            # СТРОКА 5: Шпаргалка по кнопкам (без слова 'Введите команду')
            sys.stdout.write(
                f"\033[5;1H\033[K🧭 [Клав]: n-След | p-Пред | space-Пауза | r-Рандом | e-Вкл EQ | ⬆/⬇-Громкость | q-Выход\n"
            )
            sys.stdout.flush()

        time.sleep(0.2)


def run_cli(player):
    global current_sync_status
    print("\nЗапуск асинхронного CLI режима...")
    player.load_local_tracks()

    def cli_status(text):
        global current_sync_status
        current_sync_status = text

    # Фоновый поток Яндекса теперь работает плавно
    threading.Thread(
        target=player.sync_tracks, args=(cli_status,), daemon=True
    ).start()

    if player.playlist:
        player.play_track()

    # Фоновый поток отрисовки экрана
    threading.Thread(
        target=draw_cli_timeline, args=(player,), daemon=True
    ).start()

    # ГЛАВНЫЙ АСИНХРОННЫЙ ЦИКЛ ОБРАБОТКИ НАЖАТИЙ БЕЗ ENTER
    while True:
        # Прячем курсор в конец шпаргалки, чтобы он не маячил
        sys.stdout.write("\033[5;95H")
        sys.stdout.flush()

        key = get_keypress_linux()

        if key == "n":
            player.next_track()
        elif key == "p":
            player.prev_track()
        elif key in ("space", " "):
            player.toggle_pause()
        elif key == "r":
            player.toggle_random()
        elif key == "e":
            player.eq.is_enabled = not player.eq.is_enabled
            player.save_config()
        # Изменение громкости на стрелочки без ввода цифр
        elif key == "up":  # Стрелка вверх: +5% к громкости
            new_vol = min(1.0, player.volume_level + 0.05)
            player.set_volume(new_vol)
        elif key == "down":  # Стрелка вниз: -5% к громкости
            new_vol = max(0.0, player.volume_level - 0.05)
            player.set_volume(new_vol)
        elif key in ("1", "2", "3", "4", "5", "6"):
            # Быстрое переключение пресетов EQ кнопками 1-6 на +3дБ для теста
            idx = int(key) - 1
            if player.eq.is_enabled:
                player.eq.gains[idx] = (
                    0.0 if player.eq.gains[idx] != 0.0 else 5.0
                )
                player.save_config()
        elif key == "q":
            player.save_config()
            pygame.mixer.music.stop()
            # Возвращаем терминал в стандартный режим при выходе
            sys.stdout.write("\033[2J\033[H--- До встречи! ---\n")
            sys.stdout.flush()
            break
