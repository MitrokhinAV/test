import io, threading, requests, tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC
import pygame
from core import COVER_SIZE

class GUIPlayer:
    def __init__(self, player):
        self.player = player
        self.root = tk.Tk()
        self.root.title("YaPlayer + 6Band EQ")
        self.root.geometry("450x780")
        self.root.configure(bg="#121212")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.is_dragging = False

        self.status_label = tk.Label(self.root, text="Синхронизация...", fg="#b3b3b3", bg="#121212", font=("Arial", 9))
        self.status_label.pack(pady=5)

        self.cover_label = tk.Label(self.root, bg="#282828")
        self.cover_label.pack(pady=5)
        self.set_placeholder()

        self.track_label = tk.Label(self.root, text="Ожидание...", fg="#ffffff", bg="#121212", font=("Arial", 11, "bold"), wraplength=380, justify="center")
        self.track_label.pack(pady=5)

        self.extra_info_label = tk.Label(self.root, text="", fg="#666666", bg="#121212", font=("Arial", 9))
        self.extra_info_label.pack()

        # Таймлайн
        time_frame = tk.Frame(self.root, bg="#121212")
        time_frame.pack(fill=tk.X, padx=35, pady=5)
        self.current_time_lbl = tk.Label(time_frame, text="00:00", fg="#b3b3b3", bg="#121212", font=("Arial", 9))
        self.current_time_lbl.pack(side=tk.LEFT)
        self.remaining_time_lbl = tk.Label(time_frame, text="-00:00", fg="#b3b3b3", bg="#121212", font=("Arial", 9))
        self.remaining_time_lbl.pack(side=tk.RIGHT)
        self.total_time_lbl = tk.Label(time_frame, text=" / 00:00", fg="#666666", bg="#121212", font=("Arial", 9))
        self.total_time_lbl.pack(side=tk.RIGHT)

        self.progress_scale = ttk.Scale(self.root, from_=0, to=100, orient="horizontal", length=380, command=self.on_slider_move)
        self.progress_scale.pack(pady=5)

        # Громкость
        vol_frame = tk.Frame(self.root, bg="#121212")
        vol_frame.pack(pady=5)
        tk.Label(vol_frame, text="🔈", fg="#b3b3b3", bg="#121212").pack(side=tk.LEFT, padx=5)
        self.vol_scale = ttk.Scale(vol_frame, from_=0.0, to=1.0, value=self.player.volume_level, command=self.on_volume_change, length=150)
        self.vol_scale.pack(side=tk.LEFT, padx=5)
        self.vol_percent_lbl = tk.Label(vol_frame, text=f"{int(self.player.volume_level * 100)}%", fg="#1db954", bg="#121212", font=("Arial", 9, "bold"), width=4)
        self.vol_percent_lbl.pack(side=tk.LEFT, padx=5)

        # Кнопки управления
        btn_frame = tk.Frame(self.root, bg="#121212")
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="⏮ Назад", command=lambda: self.player.prev_track(self.update_ui), bg="#282828", fg="white", bd=0, padx=12, pady=6).grid(row=0, column=0, padx=10)
        self.btn_pause = tk.Button(btn_frame, text="⏸ Пауза", command=self.pause, bg="#1db954", fg="white", bd=0, padx=18, pady=6)
        self.btn_pause.grid(row=0, column=1, padx=10)
        tk.Button(btn_frame, text="⏭ Вперед", command=lambda: self.player.next_track(self.update_ui), bg="#282828", fg="white", bd=0, padx=12, pady=6).grid(row=0, column=2, padx=10)

        # Управление режимами
        mode_frame = tk.Frame(self.root, bg="#121212")
        mode_frame.pack(pady=5)

        # Кнопка визуализатора в GUI
        vis_text = "📊 Визуализатор: ВКЛ" if self.player.visualizer.is_enabled else "📊 Визуализатор: ВЫКЛ"
        vis_color = "#1db954" if self.player.visualizer.is_enabled else "#aaaaaa"
        self.btn_vis_toggle = tk.Button(mode_frame, text=vis_text, command=self.toggle_visualizer, bg="#181818", fg=vis_color, bd=0, padx=10, pady=5)
        self.btn_vis_toggle.pack(side=tk.LEFT, padx=5)

        rand_text = "ВКЛ" if self.player.is_random else "ВЫКЛ"
        rand_color = "#1db954" if self.player.is_random else "#aaaaaa"
        self.btn_rand = tk.Button(mode_frame, text=f"🔀 Перемешать: {rand_text}", command=self.rand, bg="#181818", fg=rand_color, bd=0, padx=10, pady=5)
        self.btn_rand.pack(side=tk.LEFT, padx=5)

        # Кнопка включения эквалайзера
        eq_text = "🎛 Эквалайзер: ВКЛ" if self.player.eq.is_enabled else "🎛 Эквалайзер: ВЫКЛ"
        eq_color = "#1db954" if self.player.eq.is_enabled else "#aaaaaa"
        self.btn_eq_toggle = tk.Button(mode_frame, text=eq_text, command=self.toggle_eq, bg="#181818", fg=eq_color, bd=0, padx=10, pady=5)
        self.btn_eq_toggle.pack(side=tk.LEFT, padx=5)

        # --- ДИНАМИЧЕСКИЙ КОНТЕЙНЕР ЭКВАЛАЙЗЕРА ---
        self.eq_container = tk.Frame(self.root, bg="#121212")
        self.eq_sliders = []
        self.create_eq_sliders()
        if self.player.eq.is_enabled:
            self.eq_container.pack(pady=10, fill=tk.X, padx=20)

        threading.Thread(target=self.bg_sync, daemon=True).start()
        self.root.after(250, self.update_progress_loop)
        self.root.mainloop()

    # Добавляем визуализатор
    def toggle_visualizer(self):
        vis = self.player.visualizer
        vis.is_enabled = not vis.is_enabled
        
        if vis.is_enabled:
            self.btn_vis_toggle.config(text="📊 Визуализатор: ВКЛ", fg="#1db954")
            # Если трек уже играет, открываем окно спектрометра
            if pygame.mixer.music.get_busy() and self.player.playlist:
                track = self.player.playlist[self.player.current_index]
                vis.init_window(track.get("title", "Equalizer"))
        else:
            self.btn_vis_toggle.config(text="📊 Визуализатор: ВЫКЛ", fg="#aaaaaa")
            vis.close_window()


    def create_eq_sliders(self):
        labels = ["60Hz", "150Hz", "400Hz", "1kHz", "3kHz", "15kHz"]
        for i in range(6):
            frame = tk.Frame(self.eq_container, bg="#121212")
            frame.pack(side=tk.LEFT, expand=True, fill=tk.Y)

            slider = tk.Scale(frame, from_=10.0, to=-10.0, orient="vertical", resolution=0.5, bg="#121212", fg="#b3b3b3", highlightthickness=0, troughcolor="#282828", activebackground="#1db954", length=110, command=lambda v, idx=i: self.on_eq_slider_move(idx, v))
            slider.set(self.player.eq.gains[i])
            slider.pack()

            lbl = tk.Label(frame, text=labels[i], fg="#666666", bg="#121212", font=("Arial", 8))
            lbl.pack(pady=2)
            self.eq_sliders.append(slider)

    def toggle_eq(self):
        self.player.eq.is_enabled = not self.player.eq.is_enabled
        self.player.save_config()
        if self.player.eq.is_enabled:
            self.eq_container.pack(pady=10, fill=tk.X, padx=20)
            self.btn_eq_toggle.config(text="🎛 Эквалайзер: ВКЛ", fg="#1db954")
        else:
            self.eq_container.pack_forget()
            self.btn_eq_toggle.config(text="🎛 Эквалайзер: ВЫКЛ", fg="#aaaaaa")

    def on_eq_slider_move(self, idx, value):
        self.player.eq.gains[idx] = float(value)
        self.player.save_config()

    def on_close(self):
        self.player.save_config()
        self.root.after(150, self.root.destroy)

    def on_volume_change(self, val):
        self.player.set_volume(val)
        self.vol_percent_lbl.config(text=f"{int(float(val) * 100)}%")

    def set_placeholder(self):
        img = ImageTk.PhotoImage(Image.new("RGB", COVER_SIZE, color="#282828"))
        self.cover_label.config(image=img)
        self.cover_label.image = img

    def update_ui(self, track_data):
        self.track_label.config(text=track_data["title"])
        self.extra_info_label.config(text=self.player.get_track_extra_info(track_data))
        # Сброс ползунка
        self.progress_scale.config(to=self.player.total_seconds)
        # Пересоздаем окно визуализатора для нового трека
        if self.player.visualizer.is_enabled:
            self.player.visualizer.close_window()
            self.player.visualizer.init_window(track_data["title"])

    def bg_sync(self):
        self.player.ui_callback_reference = self.update_ui
        if self.player.playlist:
            self.root.after(0, lambda: self.player.play_track(self.update_ui))
        self.player.sync_tracks(lambda t: self.root.after(0, lambda: self.status_label.config(text=t)))

    def pause(self):
        self.player.toggle_pause()
        self.btn_pause.config(text="▶ Старт" if self.player.is_paused else "⏸ Пауза", bg="#1db954" if not self.player.is_paused else "#cd7f32")

    def rand(self):
        res = self.player.toggle_random()
        self.btn_rand.config(text=f"🔀 Перемешать: {'ВКЛ' if res else 'ВЫКЛ'}", fg="#1db954" if res else "#aaaaaa")

    def on_slider_move(self, val):
        if self.is_dragging and self.player.total_seconds > 0:
            self.player.set_position(val)

    def update_progress_loop(self):
        if self.player.playlist and self.player.total_seconds > 0:
            current = self.player.update_time_tracker()
            total = self.player.total_seconds
            if current >= total - 0.5 and not self.player.is_paused:
                self.player.next_track(self.update_ui)
            if not self.is_dragging:
                self.progress_scale.set(current)
                self.current_time_lbl.config(text=self.player.format_time(current))
                self.total_time_lbl.config(text=f" / {self.player.format_time(total)}")
                self.remaining_time_lbl.config(text=f"-{self.player.format_time(total - current)}")
            # Добавляем апдейт кадра эквалайзера на каждом тике Tkinter
            if self.player.visualizer.is_enabled:
                self.player.visualizer.update_frame()
        
        self.root.after(20, self.update_progress_loop)
