# El lab: de Windows a Linux a dCloud

La idea de fondo: **la máquina virtual es desechable, el script es el artefacto.**
Todo lo que instalas queda escrito en `bootstrap.sh`. Cuando pases a dCloud,
mueves el repositorio y corres el mismo archivo. Nada de recordar comandos.

---

## Parte 1 — levantar Ubuntu en tu Windows

### Paso 1: instala Multipass

Descárgalo de `multipass.run` e instálalo con las opciones por defecto.
Multipass es la forma más simple de tener máquinas Ubuntu en Windows.

Si tu Windows es Home y no tiene Hyper-V, el instalador te va a ofrecer
VirtualBox. Acéptalo, funciona igual para lo nuestro.

### Paso 2: crea la máquina

Abre PowerShell y corre:

```powershell
multipass launch --name lab --cpus 12 --memory 14G --disk 40G 24.04
```

Tarda unos minutos la primera vez porque descarga la imagen de Ubuntu.

**Por qué 12 CPUs y 14 GB.** Sin GPU, el modelo corre en CPU dentro del
cluster. Con 4 CPUs y 8 GB solo cabía un modelo de 3B, que no sostenía el
debate, y cada llamada tardaba 2–3 minutos. `qwen2.5:7b` necesita ~6 GB para
él solo. Referencia: la laptop de desarrollo es un i9-13900H (20 hilos, 32 GB).
Ajusta a tu máquina, dejando al menos 8 GB para Windows.

Si la VM ya existe, se cambia así (el cluster kind vuelve solo al arrancar):

```powershell
multipass stop lab
multipass set local.lab.cpus=12
multipass set local.lab.memory=14G
multipass start lab
```

Ojo: al reiniciar, **la IP de la VM puede cambiar** (`multipass info lab`).

### Paso 3: entra a la máquina

```powershell
multipass shell lab
```

A partir de aquí ya estás dentro de Linux. Todo lo que sigue se escribe ahí.

### Paso 4: trae los archivos

```bash
git clone <la-url-de-tu-repo> demo
cd demo/lab
```

Si todavía no tienes repo, puedes copiar la carpeta desde Windows con:

```powershell
multipass transfer -r C:\ruta\a\cisco-connect-demo lab:/home/ubuntu/demo
```

Pero vale la pena crear el repo desde el principio. Es lo que hace portable
todo esto.

---

## Parte 2 — instalar el lab

### Paso 5: corre el instalador

```bash
chmod +x bootstrap.sh cluster-up.sh
./bootstrap.sh
```

Lee la primera línea de la salida con atención. Dice si tu kernel tiene **BTF**.
Debe decir que está disponible. Si dice que no, avísame antes de seguir.

Al terminar, cierra la sesión y vuelve a entrar, para que Docker funcione sin
`sudo`:

```bash
exit
```
```powershell
multipass shell lab
cd demo/lab
```

### Paso 6: crea el cluster

```bash
./cluster-up.sh
```

Esto tarda varios minutos. Está creando un Kubernetes completo dentro de
contenedores, y luego instalando Cilium como su red.

Cuando termine deberías ver dos nodos en estado `Ready`.

### Paso 7: el hito — dos pods que se hablan

```bash
kubectl apply -f 01-dos-agentes.yaml
kubectl get pods -n agentes
```

Espera a que los dos digan `Running`. Luego:

```bash
kubectl exec -n agentes deploy/orquestador -- curl -s http://extractor/
```

Si ves el HTML de bienvenida de nginx, **ya está**. Eso es todo lo que había
que lograr hoy.

---

## Qué acabas de construir, y por qué importa

Parece poco: un `curl` que devuelve una página web. Pero mira lo que hay debajo.

El orquestador llamó al extractor por su **nombre**, no por su dirección. No
sabe en qué máquina está ni qué IP tiene. Kubernetes lo resolvió.

Y esa llamada no fue una función en memoria: fue **tráfico de red real** que
pasó por el kernel de Linux, donde Cilium lo vio pasar. Compruébalo:

```bash
cilium hubble port-forward &
hubble observe --namespace agentes
```

Vuelve a correr el `curl` en otra terminal y vas a ver las conexiones
apareciendo en la lista.

Esa es la frontera de la que hablábamos. Sin ella, no hay nada que inspeccionar
ni nada que bloquear. Con ella, ya tienes dónde colgar los controles.

---

## Comandos que vas a usar todo el tiempo

```bash
kubectl get pods -n agentes            # ver los agentes
kubectl logs -n agentes deploy/extractor   # ver qué dijo un agente
kubectl describe pod -n agentes <nombre>   # por qué un pod no arranca
kubectl delete -f 01-dos-agentes.yaml      # borrar los agentes
kind delete cluster --name agentes         # borrar todo el cluster
```

Si algo se enreda: borra el cluster y corre `./cluster-up.sh` otra vez.
Son unos minutos y quedas en limpio. Acostúmbrate a hacerlo sin miedo, para
eso está escrito el script.

---

## Cuando pases a dCloud

El procedimiento es el mismo:

```bash
git clone <tu-repo> && cd demo/lab
./bootstrap.sh
./cluster-up.sh
kubectl apply -f 01-dos-agentes.yaml
```

Lo único que cambia es que allá hay GPU, así que se suma vLLM. Pero la red,
las políticas y los agentes se instalan exactamente igual.

Por eso importa que todo lo que descubras estos días lo escribas en el script
en lugar de teclearlo a mano. El script es lo que viaja.
