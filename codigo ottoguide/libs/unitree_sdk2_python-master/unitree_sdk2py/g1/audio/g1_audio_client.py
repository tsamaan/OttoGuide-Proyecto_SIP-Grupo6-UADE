import json

from ...rpc.client import Client
from .g1_audio_api import *

"""
" class SportClient
"""
class AudioClient(Client):
    def __init__(self):
        super().__init__(AUDIO_SERVICE_NAME, False)
        self.tts_index = 0

    def Init(self):
        # set api version
        self._SetApiVerson(AUDIO_API_VERSION)

        # regist api
        self._RegistApi(ROBOT_API_ID_AUDIO_TTS, 0)
        self._RegistApi(ROBOT_API_ID_AUDIO_ASR, 0)
        self._RegistApi(ROBOT_API_ID_AUDIO_START_PLAY, 0)
        self._RegistApi(ROBOT_API_ID_AUDIO_STOP_PLAY, 0)
        self._RegistApi(ROBOT_API_ID_AUDIO_GET_VOLUME, 0)
        self._RegistApi(ROBOT_API_ID_AUDIO_SET_VOLUME, 0) 
        self._RegistApi(ROBOT_API_ID_AUDIO_SET_RGB_LED, 0) 

    ## API Call ##
    def TtsMaker(self, text: str, speaker_id: int):
        """
        @TASK: Enviar texto al sintetizador TTS nativo del robot Unitree G1 EDU via DDS RPC
        @INPUT: text — string a sintetizar (UTF-8); speaker_id — voz del SDK (0=default)
        @OUTPUT: Codigo de retorno del RPC (0 = exito)
        @CONTEXT: Llamado por UnitreeTTSAdapter en src/interaction/tts_unitree_client.py.
                  El indice se usa para identificar la sesion TTS en el protocolo del SDK.
        @SECURITY: Sin validacion de contenido de text; el caller debe sanear el input.

        BUG FIX (OttoGuide patch): La implementacion original era:
            self.tts_index += self.tts_index
        Esto causa crecimiento exponencial del indice (0->0->0 si arranca en 0; luego n->2n->4n
        despues del primer incremento externo), resultando en desbordamiento de entero y crash
        del protocolo DDS en sesiones largas.
        Correccion: incremento lineal += 1 con guard de overflow en INT32_MAX.
        """
        # @SECURITY: Guard de overflow: el protocolo DDS usa int32 para el indice de sesion.
        # Reiniciar a 1 al alcanzar INT32_MAX previene desbordamiento en sesiones >2B llamadas.
        _INT32_MAX = 2_147_483_647
        if self.tts_index >= _INT32_MAX:
            self.tts_index = 1
        else:
            self.tts_index += 1  # FIX: era "+= self.tts_index" (exponencial); corregido a lineal

        p = {}
        p["index"] = self.tts_index
        p["text"] = text
        p["speaker_id"] = speaker_id
        parameter = json.dumps(p)
        code, data = self._Call(ROBOT_API_ID_AUDIO_TTS, parameter)
        return code

    def GetVolume(self):
        p = {}
        parameter = json.dumps(p)
        code, data = self._Call(ROBOT_API_ID_AUDIO_GET_VOLUME, parameter)
        if code == 0:
            return code, json.loads(data)
        else:
            return code, None

    def SetVolume(self, volume: int):
        p = {}
        p["volume"] = volume
        parameter = json.dumps(p)
        code, data = self._Call(ROBOT_API_ID_AUDIO_SET_VOLUME, parameter)
        return code

    def LedControl(self, R: int, G: int, B: int):
        p = {}
        p["R"] = R
        p["G"] = G
        p["B"] = B
        parameter = json.dumps(p)
        code, data = self._Call(ROBOT_API_ID_AUDIO_SET_RGB_LED, parameter)
        return code
    
    def PlayStream(self, app_name: str, stream_id: str, pcm_data: bytes):
        param = json.dumps({"app_name": app_name, "stream_id": stream_id})
        pcm_list = list(pcm_data) 
        return self._CallRequestWithParamAndBin(ROBOT_API_ID_AUDIO_START_PLAY, param, pcm_list)
    
    def PlayStop(self, app_name: str):
        parameter = json.dumps({"app_name": app_name})
        self._Call(ROBOT_API_ID_AUDIO_STOP_PLAY, parameter)
        return 0
