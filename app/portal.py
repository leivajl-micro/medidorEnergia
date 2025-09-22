import network
import socket
import uasyncio
import uos
import machine

# Configuracion

AP_SSID = "Portal_Energia"
AP_PASSWORD = "password"
AP_IP = "192.168.4.1"

async def manejarPeticionDns(socketServidor):
    while True:
        try:
            datos, direccion = socketServidor.recvfrom(512)
            respuesta = datos[:2] + b'\x81\x80'
            respuesta += datos[4:6]
            respuesta += b'\x00\x01'
            respuesta += b'\x00\x00\x00\x00'
            respuesta += datos[12:]
            respuesta += b'\xc0\x0c'
            respuesta += b'\x00\x01'
            respuesta += b'\x00\x01'
            respuesta += b'\x00\x00\x00\x3c'
            respuesta += b'\x00\x04'
            respuesta += b'\xc0\xa8\x04\x01'
            socketServidor.sendto(respuesta, direccion)
        except OSError as e:
            if e.args[0] == 11:
                await uasyncio.sleep_ms(100)
            else:
                print("Error en el servidor DNS:", e)
                break
        except Exception as e:
            print("Error en el servidor DNS:", e)
            break

def parsearDatosFormulario(datos):
    parametros = {}
    partes = datos.split(b'&')
    for parte in partes:
        if b'=' in parte:
            clave, valor = parte.split(b'=', 1)
            valorDecodificado = ""
            i = 0
            while i < len(valor):
                if valor[i] == ord('%'):
                    hexVal = valor[i+1:i+3]
                    valorDecodificado += chr(int(hexVal, 16))
                    i += 3
                elif valor[i] == ord('+'):
                    valorDecodificado += ' '
                    i += 1
                else:
                    valorDecodificado += chr(valor[i])
                    i += 1
            parametros[clave.decode('utf-8')] = valorDecodificado
    return parametros

# Funcion web

async def manejadorWeb(lector, escritor):
    try:
        lineaPeticion = (await lector.readline()).decode('utf-8')
        metodo, url, _ = lineaPeticion.split(' ')

        encabezados = {}
        while True:
            linea = await lector.readline()
            if linea == b'\r\n':
                break
            clave, valor = linea.decode('utf-8').split(':', 1)
            encabezados[clave.strip()] = valor.strip()

        print("Peticion recibida:", metodo, url)

        if metodo == "POST":
            longitudContenido = int(encabezados.get('Content-Length', 0))
            if longitudContenido > 0:
                datosPost = await lector.read(longitudContenido)
                parametros = parsearDatosFormulario(datosPost)

                nombreRed = parametros.get('nombreRed')
                claveRed = parametros.get('claveRed')
                urlScript = parametros.get('urlScript')
                nombreDispositivo = parametros.get('nombreDispositivo')

                if nombreRed and claveRed and urlScript and nombreDispositivo:
                    with open("configuraciones.info", "w") as f:
                        f.write(f"nombreRed={nombreRed}\n")
                        f.write(f"claveRed={claveRed}\n")
                        f.write(f"url={urlScript}\n")
                        f.write(f"nombreDispositivo={nombreDispositivo}\n")
                        f.write("banderaPrincipal=0\n")
                        f.write("banderaOta=verificarActualizaciones\n")

                    try:
                        with open("confirmacion.html", "r") as f:
                            paginaHtml = f.read()
                    except OSError:
                        paginaHtml = "<h1>Error: Archivo 'confirmacion.html' no encontrado</h1>"
                        print("Error: El archivo 'confirmacion.html' no fue encontrado")

                    respuesta = "HTTP/1.1 200 OK\r\n"
                    respuesta += "Content-Type: text/html\r\n"
                    respuesta += f"Content-Length: {len(paginaHtml)}\r\n"
                    respuesta += "Connection: close\r\n\r\n"
                    respuesta += paginaHtml
                    # uso escritor porque writer.write me confundia, ahora viendolo suena raro escritor
                    escritor.write(respuesta.encode())
                    await escritor.drain()
                    escritor.close()
                    await escritor.wait_closed()

                    print("Configuracion guardada!reiniciando")
                    machine.reset()
                    return

        # Logica para precargar los campos

        nombreRedGuardado = ""
        claveRedGuardada = ""
        urlGuardada = ""
        nombreDispositivoGuardado = ""

        try:
            with open("configuraciones.info", "r") as f:
                for linea in f:
                    if linea.startswith("nombreRed="):
                        nombreRedGuardado = linea.strip().split("=")[1]
                    elif linea.startswith("claveRed="):
                        claveRedGuardada = linea.strip().split("=")[1]
                    elif linea.startswith("url="):
                        urlGuardada = linea.strip().split("=")[1]
                    elif linea.startswith("nombreDispositivo="):
                        nombreDispositivoGuardado = linea.strip().split("=")[1]
        except OSError:
            print("Archivo de configuracion no encontrado, los campos quedan vacios")

        try:
            with open("index.html", "r") as f:
                plantillaHtml = f.read()

            # Reemplazar placeholders en el HTML
            paginaHtml = plantillaHtml.replace('name="nombreRed" value=""', f'name="nombreRed" value="{nombreRedGuardado}"')
            paginaHtml = paginaHtml.replace('name="claveRed" value=""', f'name="claveRed" value="{claveRedGuardada}"')
            paginaHtml = paginaHtml.replace('name="urlScript" value=""', f'name="urlScript" value="{urlGuardada}"')
            paginaHtml = paginaHtml.replace('name="nombreDispositivo" value=""', f'name="nombreDispositivo" value="{nombreDispositivoGuardado}"')

        except OSError:
            paginaHtml = "<h1>Error: Archivo 'index.html' no encontrado</h1>"
            print("Error: El archivo 'index.html' no fue encontrado")

        respuesta = "HTTP/1.1 200 OK\r\n"
        respuesta += "Content-Type: text/html\r\n"
        respuesta += f"Content-Length: {len(paginaHtml)}\r\n"
        respuesta += "Connection: close\r\n\r\n"
        respuesta += paginaHtml

        escritor.write(respuesta.encode())
        await escritor.drain()
        escritor.close()
        await escritor.wait_closed()

    except Exception as e:
        print("Error en el servidor web:", e)

# Funcion main()

async def main():
    print("Iniciando el portal cautivo")
    network.WLAN(network.STA_IF).active(False)
    network.WLAN(network.AP_IF).active(False)

    ap_if = network.WLAN(network.AP_IF)
    ap_if.config(essid=AP_SSID, password=AP_PASSWORD)
    ap_if.ifconfig((AP_IP, '255.255.255.0', AP_IP, AP_IP))
    ap_if.active(True)

    print("AP '", AP_SSID, "' iniciado en la IP", ap_if.ifconfig()[0])

    dnsSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dnsSocket.setblocking(False)
    dnsSocket.bind(("0.0.0.0", 53))

    tareaDns = uasyncio.create_task(manejarPeticionDns(dnsSocket))
    servidorWeb = uasyncio.start_server(manejadorWeb, "0.0.0.0", 80)

    await uasyncio.gather(tareaDns, servidorWeb)

if __name__ == '__main__':
    uasyncio.run(main())