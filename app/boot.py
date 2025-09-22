import network
import time
import machine
import uos
import uasyncio
import urequests
import json
import senko

# Configuracion de OTA
repositorioOtaUrl = "leivajl-micro/medidorEnergia"
actualizarArchivos = ["boot.py", "main.py", "panel.html"]

# Funciones de utilidad y configuracion
def cargarConfiguracion():
    try:
        with open("configuraciones.info", "r") as f:
            lineas = f.readlines()
            configuracion = {}
            for linea in lineas:
                if "=" in linea:
                    clave, valor = linea.strip().split("=", 1)
                    configuracion[clave] = valor
            return configuracion
    except OSError:
        return {}

def guardarConfiguracion(configuracion):
    try:
        with open("configuraciones.info", "w") as f:
            for clave, valor in configuracion.items():
                f.write(f"{clave}={valor}\n")
    except Exception as e:
        print(f"Error al guardar la configuracion: {e}")

# Logica de Banderas y Arranque
print("Iniciando boot")

interfazSta = network.WLAN(network.STA_IF)
configuracion = cargarConfiguracion()
banderaOta = configuracion.get("banderaOta", "verificarActualizaciones")
banderaPrincipal = configuracion.get("banderaPrincipal", "1")

#Logica OTA
if banderaOta == "verificarActualizaciones":
    print("Bandera de OTA: verificarActualizaciones")

    # Intenta conectar a la red para actualizar
    interfazSta.active(True)
    nombreRed = configuracion.get("nombreRed")
    claveRed = configuracion.get("claveRed")
    interfazSta.connect(nombreRed, claveRed)

    tiempoInicio = time.time()
    while not interfazSta.isconnected() and (time.time() - tiempoInicio) < 15:
        time.sleep(1)
        print(".", end="")
    print("")

    if interfazSta.isconnected():
        print("Conexion wifi exitosa. Buscando actualizaciones OTA.")
        actualizadorOta = senko.Senko(user=repositorioOtaUrl.split('/')[0], repo=repositorioOtaUrl.split('/')[1], files=actualizarArchivos)

        if actualizadorOta.fetch():
            print("¡se encontro una nueva version! Descargando y estableciendo bandera para aplicar")
            actualizadorOta.update()
            configuracion["banderaOta"] = "aplicarActualizacion"
            guardarConfiguracion(configuracion)
            machine.reset()
        else:
            print("No se encontraron nuevas actualizaciones")
            configuracion["banderaOta"] = "aplicacionPrincipal"
            guardarConfiguracion(configuracion)
    else:
        print("Error al conectar, no se puede buscar actualizaciones")
        configuracion["banderaOta"] = "aplicacionPrincipal"
        guardarConfiguracion(configuracion)

    # Reiniciar
    machine.reset()

elif banderaOta == "aplicarActualizacion":
    print("Bandera de OTA: aplicarActualizacion")

    interfazSta.active(True)
    nombreRed = configuracion.get("nombreRed")
    claveRed = configuracion.get("claveRed")
    interfazSta.connect(nombreRed, claveRed)

    actualizadorOta = senko.Senko(user=repositorioOtaUrl.split('/')[0], repo=repositorioOtaUrl.split('/')[1], files=actualizarArchivos)

    if actualizadorOta.update():
        print("Actualizacion aplicada, reiniciando")
    else:
        print("Error al aplicar la actualizacion")

    configuracion["banderaOta"] = "aplicacionPrincipal"
    guardarConfiguracion(configuracion)
    machine.reset()

elif banderaOta == "aplicacionPrincipal":
    print("Bandera de OTA: aplicacionPrincipal")
    configuracion["banderaOta"] = "verificarActualizaciones"
    guardarConfiguracion(configuracion)

    # logica OTA termina aca. se ejecuta la logica del portal cautivo

    import portal

    if banderaPrincipal == "1":
        print("Bandera Principal es 1. Iniciando portal cautivo")
        interfazSta.active(False) # hay que asegurarse que el STA este inactivo
        # La logica del portal esta en un bucle sincrono para que no se salga hasta que se conecte
        while not interfazSta.isconnected():
            uasyncio.run(portal.main())
            time.sleep(1)

        configuracion['banderaPrincipal'] = '0'
        guardarConfiguracion(configuracion)
        print("Conexion exitosa, reiniciando")
        time.sleep(3)
        machine.reset()

    elif banderaPrincipal == "0":
        print("Bandera Principal es 0, intentando conectar a la red wifi")
        nombreRed = configuracion.get("nombreRed")
        claveRed = configuracion.get("claveRed")

        interfazSta.active(True)
        interfazSta.connect(nombreRed, claveRed)

        tiempoInicio = time.time()
        while not interfazSta.isconnected() and (time.time() - tiempoInicio) < 15:
            time.sleep(1)

        if interfazSta.isconnected():
            print("conexion wifi, corre main.py")
            # fin del boot.py
        else:
            print("Error de conexion cambiando bandera a 1 y reiniciando para entrar en el portal cautivo")
            configuracion['banderaPrincipal'] = '1'
            guardarConfiguracion(configuracion)
            time.sleep(3)
            machine.reset()
    else:
        print("no se encontro el archivo de configuracion, arrancando portal cautivo")
        interfazSta.active(False)
        while not interfazSta.isconnected():
            uasyncio.run(portal.main())
            time.sleep(1)
        configuracion = cargarConfiguracion()
        configuracion['banderaPrincipal'] = '0'
        guardarConfiguracion(configuracion)
        print("Portal Cautivo terminado, reiniciando para aplicar la configuracion")
        time.sleep(3)
        machine.reset()