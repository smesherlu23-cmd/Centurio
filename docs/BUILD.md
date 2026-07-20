# Сборка Centurio

## Запуск из исходников

```bash
pip install -r requirements.txt
python main.py
```

Диагностика окружения (полезно при проблемах — покажет, что найдено и что доступно):

```bash
python -m app.diagnose
```

## Сборка нативного приложения (Flet)

Требуется установленный **Flutter SDK** (+ на Windows — Visual Studio с
компонентами C++). Flet сам вызывает Flutter.

```bash
pip install "flet[all]==0.28.3"
python -m app.iconify           # сгенерировать assets/icon.png
flet build windows              # или: macos / linux
```

Результат — папка `build/windows` (`Centurio.exe` + рантайм).

## Установщик для Windows (Inno Setup)

1. Соберите приложение (`flet build windows`).
2. Установите [Inno Setup 6](https://jrsoftware.org/isdl.php).
3. Скомпилируйте установщик:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\centurio.iss
```

Готовый файл — `installer\Output\CenturioSetup.exe`. Установщик создаёт ярлык
в меню «Пуск», по желанию — на рабочем столе, и опцию «запускать при входе».

## Автоматическая сборка (GitHub Actions)

`.github/workflows/build-windows.yml` собирает приложение и установщик на
`windows-latest`. Запуск: вкладка **Actions → Build Windows installer → Run
workflow**, либо пуш тега `vX.Y.Z`. Артефакты (`CenturioSetup.exe` и папка
приложения) появятся в результатах запуска.
