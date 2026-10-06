import os

# Sin ruido de fondo en los tests: sus errores aleatorios los volverían inestables.
os.environ["BACKGROUND_NOISE"] = "off"
