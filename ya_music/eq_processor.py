import numpy as np
from scipy.signal import butter, lfilter

class Equalizer:
    def __init__(self):
        self.is_enabled = False
        # 6 полос: Бас, Мид-бас, Нижняя середина, Середина, Верхняя середина, Высокие
        self.bands = [60, 150, 400, 1000, 3000, 15000]
        # Коэффициенты усиления для каждой полосы (от -10 до +10 дБ, 0 — нейтрально)
        self.gains = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.sample_rate = 44100

    def _butter_bandpass(self, lowcut, highcut, fs, order=2):
        nyq = 0.5 * fs
        low = lowcut / nyq
        high = highcut / nyq
        # Ограничиваем частоты в пределах диапазона Найквиста
        low = max(0.001, min(0.999, low))
        high = max(0.002, min(0.999, high))
        b, a = butter(order, [low, high], btype='band')
        return b, a

    def process_audio_chunk(self, data_bytes):
        """Применяет 6-полосный фильтр к сырому куску аудио-байтов"""
        if not self.is_enabled or all(g == 0.0 for g in self.gains):
            return data_bytes

        # Конвертируем байты PCM16 в массив numpy
        audio_data = np.frombuffer(data_bytes, dtype=np.int16).astype(np.float32)
        
        # Результирующий сигнал
        out_data = np.zeros_like(audio_data)

        # Применяем фильтры для каждой частотной полосы
        for i, (freq, gain) in enumerate(zip(self.bands, self.gains)):
            # Задаем ширину полосы пропускания
            lowcut = freq * 0.7
            highcut = freq * 1.4
            
            try:
                b, a = self._butter_bandpass(lowcut, highcut, self.sample_rate)
                band_signal = lfilter(b, a, audio_data)
                
                # Переводим дБ в линейный коэффициент усиления
                linear_gain = 10 ** (gain / 20.0)
                out_data += band_signal * (linear_gain - 1.0)
            except:
                continue

        # Смешиваем обработанный сигнал с оригиналом и нормализуем
        final_signal = audio_data + out_data
        final_signal = np.clip(final_signal, -32768, 32767)
        
        return final_signal.astype(np.int16).tobytes()
