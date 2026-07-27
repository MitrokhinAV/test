from core import MusicPlayer
from gui import GUIPlayer
from cli import run_cli

if __name__ == "__main__":
    player = MusicPlayer()

    print("Выберите интерфейс:")
    print("1. Графический плеер с обложками (GUI)")
    print("2. Легкий текстовый плеер (CLI)")
    choice = input("Введите 1 или 2: ").strip()

    if choice == "1":
        GUIPlayer(player)
    else:
        run_cli(player)
