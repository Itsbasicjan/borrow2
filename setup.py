# setup.py

# ... (andere imports und Code bleiben gleich) ...
import os # Sicherstellen, dass os importiert ist
import importlib.util # Sicherstellen, dass importlib.util importiert ist
import setuptools # Sicherstellen, dass setuptools importiert ist

# ... (Code zum Lesen der Version und README bleibt gleich) ...
# Lies die Version aus meinplugin/__init__.py
# Stelle sicher, dass diese Datei existiert und PLUGIN_VERSION definiert!
init_py_path = os.path.join(os.path.dirname(__file__), 'meinplugin', '__init__.py')
if not os.path.exists(init_py_path):
    # Erstelle eine __init__.py, falls sie fehlt, mit der Version
    with open(init_py_path, 'w') as f:
        # Setze hier die aktuelle Version deines Plugins ein
        f.write("PLUGIN_VERSION = '0.3.1'\n") # Beispielversion

module_path = os.path.join(os.path.dirname(__file__), "meinplugin", "__init__.py")
spec = importlib.util.spec_from_file_location("meinplugin_init", module_path) # Geänderter Modulname für importlib
meinplugin_init = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meinplugin_init)


with open('README.md', encoding='utf-8') as f:
    long_description = f.read()

setuptools.setup(
    name="meinplugin", # Der Name des Pakets (kann bleiben)
    version=meinplugin_init.PLUGIN_VERSION, # Version aus __init__.py
    author="Jan Schüler",
    author_email="jandeluxe96@gmail.com",
    description="A loan management plugin for InvenTree", # Bessere Beschreibung
    long_description=long_description,
    long_description_content_type='text/markdown',
    license="MIT",
    # Finde automatisch das 'meinplugin' Verzeichnis
    packages=setuptools.find_packages(),
    # Wichtig, damit Templates, statische Dateien etc. mitkopiert werden
    include_package_data=True,
    install_requires=[
        # Keine spezifischen Abhängigkeiten für dieses Beispiel
        # Hier könnten z.B. 'requests' stehen, wenn du externe APIs nutzt
    ],
    setup_requires=[
        "wheel",
        "twine",
    ],
    python_requires=">=3.9",
    entry_points={
        "inventree_plugins": [
            # Format: BELIEBIGER_INTERNER_NAME = PFAD.ZUR.PYTHON_DATEI:KLASSENNAME
            "LoanPlugin = meinplugin.core:LoanPlugin" # <-- KORRIGIERT!
        ]
    },
)