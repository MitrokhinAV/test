import os
import threading
import numpy as np
import pygame
from pydub import AudioSegment

class MusicVisualizer:
    def __init__(self, num_bars=25, win_width=800, win_height=300, fps=60):
        self.num_bars = num_bars
        self.win_width = win_width
        self.win_height = win_height
        self.fps = fps
        
        # Настройки анимации
        self.fall_speed = 0.8     
        self.block_size = 5        
        self.max_bar_height = win_height - 60
        
        self.peaks = np.zeros(num_bars)
        self.smoothed_heights = np.zeros(num_bars)
        self.matrix = None
        
        self.is_enabled = False
        self.is_ready = False
        self._screen = None
        self._clock = None
        self._running = False
        self.is_paused_check = None

    def start_analysis_async(self, file_path, is_paused_callback_func=None):
        """Мгновенный асинхронный анализ трека через pydub"""
        self.is_ready = False
        self.matrix = None
        if not os.path.exists(file_path):
            return
        
        self.is_paused_check = is_paused_callback_func
        thread = threading.Thread(target=self._analyze_worker, args=(file_path,), daemon=True)
        thread.start()

    def _analyze_worker(self, file_path):
        try:
            audio = AudioSegment.from_file(file_path, format="mp3")
            audio = audio.set_frame_rate(22050).set_channels(1)
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
            
            hop_length = int(22050 / self.fps)
            n_fft = 2048
            
            num_frames = int((len(samples) - n_fft) / hop_length) + 1
            if num_frames <= 0:
                return
                
            raw_frames = np.array([samples[i*hop_length : i*hop_length + n_fft] for i in range(num_frames)])
            window = np.hanning(n_fft)
            fft_matrix = np.abs(np.fft.rfft(raw_frames * window, axis=1)).T
            
            with np.errstate(divide='ignore'):
                stft_db = 20 * np.log10(fft_matrix + 1e-5)
            stft_norm = (stft_db - stft_db.min()) / (stft_db.max() - stft_db.min() + 1e-5)
            
            freq_bins = np.logspace(0, np.log10(stft_norm.shape[0]), self.num_bars + 1).astype(int)
            freq_bins = np.clip(freq_bins, 0, stft_norm.shape[0] - 1)
            
            self.matrix = np.zeros((self.num_bars, stft_norm.shape[1]))
            for i in range(self.num_bars):
                start, end = freq_bins[i], freq_bins[i+1]
                if start == end: end += 1
                self.matrix[i] = np.mean(stft_norm[start:end, :], axis=0)
                
            self.peaks = np.zeros(self.num_bars)
            self.smoothed_heights = np.zeros(self.num_bars)
            self.is_ready = True
        except Exception as e:
            print(f"[Visualizer FFT Error] {e}")

    def _get_gradient_color(self, current_y):
        """Цвет градиента: Зеленый -> Синий -> Насыщенный Красный на вершине"""
        ratio = current_y / self.max_bar_height
        ratio = min(max(ratio, 0.0), 1.0)
        
        if ratio < 0.4:
            factor = ratio / 0.4
            return (0, int(220 * (1 - factor) + 30 * factor), int(50 * (1 - factor) + 240 * factor))
        elif ratio < 0.75:
            factor = (ratio - 0.4) / 0.35
            return (int(200 * factor), 30, int(240 * (1 - factor) + 50 * factor))
        else:
            factor = (ratio - 0.75) / 0.25
            return (255, int(40 * (1 - factor)), int(50 * (1 - factor)))

    def init_window(self, track_title="Equalizer"):
        if not self.is_enabled:
            return
        pygame.init()
        self._screen = pygame.display.set_mode((self.win_width, self.win_height))
        pygame.display.set_caption(f"🎛️ Эквалайзер — {track_title}")
        self._clock = pygame.time.Clock()
        self._running = True

    def close_window(self):
        self._running = False
        self._screen = None

    def update_frame(self):
        if not self.is_enabled or not self._running or self._screen is None:
            return
            
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.close_window()
                return

        self._screen.fill((12, 13, 19))

        if not self.is_ready or self.matrix is None:
            font = pygame.font.SysFont("Arial", 14)
            text = font.render("Мгновенный рендеринг спектра...", True, (120, 120, 120))
            self._screen.blit(text, (30, self.win_height // 2))
            pygame.display.flip()
            return

        is_paused = False
        if self.is_paused_check:
            is_paused = self.is_paused_check()

        current_time_ms = pygame.mixer.music.get_pos()
        current_frame = int((current_time_ms / 1000.0) * self.fps)
        
        # --- ГЕОМЕТРИЯ (СТОЛБИКИ В 2 РАЗА УЖЕ + ЦЕНТРОВАНИЕ) ---
        bar_padding = 6  
        full_bar_width = (self.win_width - (bar_padding * (self.num_bars + 1))) // self.num_bars
        bar_width = max(full_bar_width // 2, 4) 
        
        total_equalizer_width = (bar_width + bar_padding) * self.num_bars - bar_padding
        start_x_offset = (self.win_width - total_equalizer_width) // 2
        base_y = self.win_height - 30

        for i in range(self.num_bars):
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем по оси кадров matrix.shape[1]
            if is_paused or current_frame >= self.matrix.shape[1] or current_time_ms == -1:
                target_height = 0
            else:
                target_height = self.matrix[i, current_frame] * self.max_bar_height
            
            self.smoothed_heights[i] += (target_height - self.smoothed_heights[i]) * 0.25
            h = int(self.smoothed_heights[i])

            x = start_x_offset + i * (bar_width + bar_padding)
            
            if h > self.peaks[i]: self.peaks[i] = h
            else: self.peaks[i] -= self.fall_speed
            self.peaks[i] = max(self.peaks[i], 0)

            for block_y in range(0, h, self.block_size + 1):
                y_coord = base_y - block_y
                color = self._get_gradient_color(block_y)
                pygame.draw.rect(self._screen, color, (x, y_coord, bar_width, self.block_size))

            peak_y_coord = base_y - int(self.peaks[i]) - 5
            peak_color = self._get_gradient_color(self.peaks[i])
            pygame.draw.rect(self._screen, peak_color, (x, peak_y_coord, bar_width, 2))

        pygame.draw.line(self._screen, (25, 30, 45), (0, base_y + 10), (self.win_width, base_y + 10), 1)
        pygame.display.flip()
        self._clock.tick(self.fps)
