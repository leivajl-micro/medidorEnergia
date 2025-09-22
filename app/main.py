import network
import uos
import uasyncio
import urequests
import machine
import json
import time
import socket
from pzem import PZEM
import gc

# Configuracion de Firmware
VERSION = "1.0.7"

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

# Funciones de reconexion de la red
def verificarYReconectar():
    interfazSta = network.WLAN(network.STA_IF)
    if not interfazSta.isconnected():
        print("La conexion wifi se corto, intentando reconectar")
        interfazSta.active(True)
        configuracion = cargarConfiguracion()
        nombreRed = configuracion.get("nombreRed")
        claveRed = configuracion.get("claveRed")
        interfazSta.connect(nombreRed, claveRed)

        tiempoInicio = time.time()
        while not interfazSta.isconnected() and (time.time() - tiempoInicio) < 30:
            time.sleep(1)
            print(".", end="")
        print("")

        if interfazSta.isconnected():
            print("Reconexion exitosa!!")
        else:
            print("Error en la reconexion, reiniciando para forzar el portal cautivo")
            configuracion['banderaPrincipal'] = '1'
            guardarConfiguracion(configuracion)
            time.sleep(3)
            machine.reset()

# Funciones de envio de datos
def enviarDatosSensorGoogleSheets(
    url,
    voltaje,
    corriente,
    potenciaActiva,
    energia,
    frecuencia,
    factorPotencia,
    nombreDispositivo,
    ipDispositivo
):
    try:
        cadenaConsulta = (
            f"?voltaje={voltaje}"
            f"&corriente={corriente}"
            f"&potenciaActiva={potenciaActiva}"
            f"&energia={energia}"
            f"&frecuencia={frecuencia}"
            f"&factorPotencia={factorPotencia}"
            f"&nombreDispositivo={nombreDispositivo}"
            f"&ip={ipDispositivo}"
        )
        urlConDatos = url + cadenaConsulta
        respuesta = urequests.get(urlConDatos, timeout=10)

        if respuesta.status_code == 200:
            print("Datos enviados!!")
        else:
            print(f"Error al enviar datos, codigo de estado: {respuesta.status_code}")

        respuesta.close()
        gc.collect()
    except Exception as e:
        print("Error al enviar datos:", e)

# Funciones de servidor web
datosSensor = {
    "voltaje": 0.0,
    "corriente": 0.0,
    "potencia": 0.0,
    "energia": 0.0,
    "frecuencia": 0.0,
    "factor": 0.0
}

async def reiniciarEnergiaYActualizarDatos():
    global datosSensor
    print("Reiniciando el contador de energia")
    if pzem:
        pzem.resetEnergy()
    datosSensor["energia"] = 0.0
    print("El contador de energia se reinicio")

async def manejadorWeb(lector, escritor):
    nombreDispositivo = globals().get('nombreDispositivoDesdeConfig', 'Dispositivo Desconocido')

    try:
        lineaPeticion = await lector.readline()
        if not lineaPeticion:
            return

        partesPeticion = lineaPeticion.decode().split(' ')
        metodoPeticion = partesPeticion[0]
        urlPeticion = partesPeticion[1]

        encabezados = {}
        while True:
            linea = await lector.readline()
            if not linea or linea == b'\r\n':
                break
            nombreEncabezado, valorEncabezado = linea.decode().strip().split(': ', 1)
            encabezados[nombreEncabezado.lower()] = valorEncabezado

        if metodoPeticion == 'GET':
            if urlPeticion == '/':
                with open('panel.html', 'r') as f:
                    html = f.read()
                htmlConNombre = html.replace('{{NOMBRE_DISPOSITIVO}}', nombreDispositivo)

                escritor.write('HTTP/1.1 200 OK\r\n')
                escritor.write('Content-Type: text/html\r\n')
                escritor.write('Connection: close\r\n\r\n')
                escritor.write(htmlConNombre.encode('utf-8'))
            elif urlPeticion == '/data':
                escritor.write('HTTP/1.1 200 OK\r\n')
                escritor.write('Content-Type: application/json\r\n')
                escritor.write('Connection: close\r\n\r\n')
                escritor.write(json.dumps(datosSensor).encode('utf-8'))
            elif urlPeticion == '/forzarPortal':
                print("Pedido de forzar el portal cautivo")
                configuracion = cargarConfiguracion()
                configuracion['banderaPrincipal'] = '1'
                guardarConfiguracion(configuracion)
                escritor.write('HTTP/1.1 200 OK\r\n')
                escritor.write('Content-Type: text/plain\r\n')
                escritor.write('Connection: close\r\n\r\n')
                escritor.write(b"OK. Reiniciando para entrar en modo Portal Cautivo.")

                await escritor.drain()
                escritor.close()
                await escritor.wait_closed()
                time.sleep(1)
                machine.reset()
            else:
                escritor.write('HTTP/1.1 404 Not Found\r\n\r\n')
        elif metodoPeticion == 'POST':
            if urlPeticion == '/reiniciarEnergia':
                print("Pedido de reinicio de energia")
                await reiniciarEnergiaYActualizarDatos()
                escritor.write('HTTP/1.1 200 OK\r\n')
                escritor.write('Content-Type: text/plain\r\n')
                escritor.write('Connection: close\r\n\r\n')
                escritor.write(b"OK")
            elif urlPeticion == '/guardarIntervalo':
                longitudContenido = int(encabezados.get('content-length', 0))
                datosPost = await lector.read(longitudContenido)
                try:
                    datos = json.loads(datosPost.decode('utf-8'))
                    nuevoIntervalo = int(datos.get('intervalo', 300))

                    if nuevoIntervalo < 30:
                        escritor.write('HTTP/1.1 400 Bad Request\r\n\r\n')
                        escritor.write(b"El intervalo debe ser de al menos 30 segundos.")# Es necesario ya que con valores menores comienza a fallar
                        return

                    configuracion = cargarConfiguracion()
                    configuracion['intervalo'] = str(nuevoIntervalo)
                    guardarConfiguracion(configuracion)

                    escritor.write('HTTP/1.1 200 OK\r\n')
                    escritor.write('Content-Type: text/plain\r\n')
                    escritor.write('Connection: close\r\n\r\n')
                    escritor.write(b"OK")
                except (ValueError, TypeError, json.JSONDecodeError) as e:
                    print(f"Error procesando el JSON: {e}")
                    escritor.write('HTTP/1.1 400 Bad Request\r\n\r\n')
                    escritor.write(b"Error en el formato de datos JSON.")
            else:
                escritor.write('HTTP/1.1 404 Not Found\r\n\r\n')
        else:
            escritor.write('HTTP/1.1 405 Method Not Allowed\r\n\r\n')
    except Exception as e:
        print(f"Error en el servidor web: {e}")
    finally:
        await escritor.drain()
        escritor.close()
        await escritor.wait_closed()
        gc.collect()

#Tareas asincronicas
async def tareaDatosYWeb(urlConfig, nombreDispositivoConfig, ipDispositivo):
    global datosSensor

    while True:
        verificarYReconectar()
        interfazSta = network.WLAN(network.STA_IF)

        if interfazSta.isconnected():
            if pzem:
                try:
                    pzem.read()
                    datosSensor["voltaje"] = pzem.getVoltage()
                    datosSensor["corriente"] = pzem.getCurrent()
                    datosSensor["potencia"] = pzem.getActivePower()
                    datosSensor["energia"] = pzem.getActiveEnergy()
                    datosSensor["frecuencia"] = pzem.getFrequency()
                    datosSensor["factor"] = pzem.getPowerFactor()

                    print("Exito al leer el sensor, enviando datos a google sheets")
                    enviarDatosSensorGoogleSheets(
                        urlConfig,
                        datosSensor["voltaje"],
                        datosSensor["corriente"],
                        datosSensor["potencia"],
                        datosSensor["energia"],
                        datosSensor["frecuencia"],
                        datosSensor["factor"],
                        nombreDispositivoConfig,
                        ipDispositivo
                    )
                except Exception as e:
                    print(f"Error al leer datos del sensor: {e}.")

            else:
                print("No se pudo conectar con el sensor, imposible enviar datos")
        else:
            print("Error al reconectar")

        configuracion = cargarConfiguracion()
        tiempoEspera = int(configuracion.get("intervalo", 300))
        print(f"Esperando {tiempoEspera} segundos para el siguiente envio")
        await uasyncio.sleep(tiempoEspera)
        gc.collect()

# Logica de arranque
print("Arrancando el main.py")

# Verificar que la conexion este activa antes de empezar
verificarYReconectar()

interfazSta = network.WLAN(network.STA_IF)
if interfazSta.isconnected():
    print("El boot.py se conecto")
    configuracion = cargarConfiguracion()
    urlDesdeConfig = configuracion.get("url")
    nombreDispositivoDesdeConfig = configuracion.get("nombreDispositivo")
    ipDispositivo = interfazSta.ifconfig()[0]

    print(f"IP del dispositivo: {ipDispositivo}")
    print(f"Nombre del dispositivo: {nombreDispositivoDesdeConfig}")
    print(f"Versión de Firmware: {VERSION}")

    try:
        uart2 = machine.UART(2, tx=17, rx=16)
        pzem = PZEM(uart2)
        print("Sensor PZEM-004T inicializado en UART2")
    except Exception as e:
        print(f"Error al inicializar el sensor: {e}")
        pzem = None

    globals()['nombreDispositivoDesdeConfig'] = nombreDispositivoDesdeConfig

    try:
        tareaServidorWeb = uasyncio.start_server(manejadorWeb, "0.0.0.0", 80)
        instanciaTareaDatosYWeb = tareaDatosYWeb(urlDesdeConfig, nombreDispositivoDesdeConfig, ipDispositivo)

        uasyncio.run(uasyncio.gather(tareaServidorWeb, instanciaTareaDatosYWeb))

    except Exception as e:
        print(f"Error en el bucle principal de uasyncio: {e}")
        print("Reiniciando")
        time.sleep(3)
        machine.reset()

else:
    print("Error: El boot.py no pudo conectarse, esto es malo, reiniciando")

    machine.reset()
