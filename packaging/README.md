# Empaquetar Eclipse: ejecutable + instalador de Windows

Dos pasos: bundlear la app en un `.exe` parado solo (PyInstaller), y después
envolverlo en un instalador de Windows (Inno Setup).

## 1. Construir el ejecutable

```bat
.venv\Scripts\python -m pip install pyinstaller
scripts\build_exe.bat
```

Salida: `dist\eclipse-agent\eclipse-agent.exe` — un bundle en carpeta que corre
sin necesidad de Python ni venv.

Probalo:

```bat
dist\eclipse-agent\eclipse-agent.exe diagnostics
dist\eclipse-agent\eclipse-agent.exe settings
```

## 2. Construir el instalador

Instalá [Inno Setup 6](https://jrsoftware.org/isdl.php) y compilá el script:

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\eclipse-setup.iss
```

Salida: `dist\installer\eclipse-setup-0.1.0.exe` — el instalador con página de
licencia (MIT), selección de idioma, opciones (ícono de escritorio, iniciar con
Windows) y accesos directos a la app de configuración. Instala por usuario, sin
permisos de administrador.

## Notas

- La app de configuración (`eclipse-agent.exe settings`) es la entrada principal;
  el modelo de IA, la voz, las credenciales y los MCP se ajustan ahí después de
  instalar.
- En modo empaquetado, los subcomandos se despachan por el propio `.exe`
  (el arranque del daemon lo maneja vía `sys.frozen`).
- `collect_data_files('eclipse_agent')` en el `.spec` incluye el HTML de la GUI.
- Las rutas del `.spec` se resuelven desde la raíz del repo vía `SPECPATH`.
