"""
Davis Vantage Pro and Pro2 Service

Abstract:
Allows data query of Davis Vantage Pro and Pro2 devices via serial port
interface.  The primary implemented serial commands supported are LOOP and
DMPAFT.

The LOOP command can acquire all real-time data points. The DMPAFT command is
used to acquire periodic high/low data.

All data is returned in a dict structure with value/key pairs. Periodic data is
only captured once per period. When not active, the keys for periodic data are
not present in the results.

Author: Patrick C. McGinty (pyweather@tuxcoder.com)
Date: 2010-06-025

Original Author: Christopher Blunck (chris@wxnet.org)
Date: 2006-03-27
"""

from ._struct import Struct
from ..units import *
from .station import *

import asyncio
import logging
import serial
import struct
import time
from array import array
import datetime as dt

log = logging.getLogger(__name__)

# public interfaces for module
__all__ = ['VantagePro', 'NoDeviceException']

READ_DELAY = 5
BAUD = 19200


def log_raw(msg, raw):
    log.debug(msg + ': ' + raw.decode())


class NoDeviceException(Exception):
    pass


class NoNewRecordsException(Exception):
    pass


class VProCRC(object):
    """
    Implements CRC algorithm, necessary for encoding and verifying data from
    the Davis Vantage Pro unit.
    """

    CRC_TABLE = (
        0x0, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7,
        0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef,
        0x1231, 0x210, 0x3273, 0x2252, 0x52b5, 0x4294, 0x72f7, 0x62d6,
        0x9339, 0x8318, 0xb37b, 0xa35a, 0xd3bd, 0xc39c, 0xf3ff, 0xe3de,
        0x2462, 0x3443, 0x420, 0x1401, 0x64e6, 0x74c7, 0x44a4, 0x5485,
        0xa56a, 0xb54b, 0x8528, 0x9509, 0xe5ee, 0xf5cf, 0xc5ac, 0xd58d,
        0x3653, 0x2672, 0x1611, 0x630, 0x76d7, 0x66f6, 0x5695, 0x46b4,
        0xb75b, 0xa77a, 0x9719, 0x8738, 0xf7df, 0xe7fe, 0xd79d, 0xc7bc,
        0x48c4, 0x58e5, 0x6886, 0x78a7, 0x840, 0x1861, 0x2802, 0x3823,
        0xc9cc, 0xd9ed, 0xe98e, 0xf9af, 0x8948, 0x9969, 0xa90a, 0xb92b,
        0x5af5, 0x4ad4, 0x7ab7, 0x6a96, 0x1a71, 0xa50, 0x3a33, 0x2a12,
        0xdbfd, 0xcbdc, 0xfbbf, 0xeb9e, 0x9b79, 0x8b58, 0xbb3b, 0xab1a,
        0x6ca6, 0x7c87, 0x4ce4, 0x5cc5, 0x2c22, 0x3c03, 0xc60, 0x1c41,
        0xedae, 0xfd8f, 0xcdec, 0xddcd, 0xad2a, 0xbd0b, 0x8d68, 0x9d49,
        0x7e97, 0x6eb6, 0x5ed5, 0x4ef4, 0x3e13, 0x2e32, 0x1e51, 0xe70,
        0xff9f, 0xefbe, 0xdfdd, 0xcffc, 0xbf1b, 0xaf3a, 0x9f59, 0x8f78,
        0x9188, 0x81a9, 0xb1ca, 0xa1eb, 0xd10c, 0xc12d, 0xf14e, 0xe16f,
        0x1080, 0xa1, 0x30c2, 0x20e3, 0x5004, 0x4025, 0x7046, 0x6067,
        0x83b9, 0x9398, 0xa3fb, 0xb3da, 0xc33d, 0xd31c, 0xe37f, 0xf35e,
        0x2b1, 0x1290, 0x22f3, 0x32d2, 0x4235, 0x5214, 0x6277, 0x7256,
        0xb5ea, 0xa5cb, 0x95a8, 0x8589, 0xf56e, 0xe54f, 0xd52c, 0xc50d,
        0x34e2, 0x24c3, 0x14a0, 0x481, 0x7466, 0x6447, 0x5424, 0x4405,
        0xa7db, 0xb7fa, 0x8799, 0x97b8, 0xe75f, 0xf77e, 0xc71d, 0xd73c,
        0x26d3, 0x36f2, 0x691, 0x16b0, 0x6657, 0x7676, 0x4615, 0x5634,
        0xd94c, 0xc96d, 0xf90e, 0xe92f, 0x99c8, 0x89e9, 0xb98a, 0xa9ab,
        0x5844, 0x4865, 0x7806, 0x6827, 0x18c0, 0x8e1, 0x3882, 0x28a3,
        0xcb7d, 0xdb5c, 0xeb3f, 0xfb1e, 0x8bf9, 0x9bd8, 0xabbb, 0xbb9a,
        0x4a75, 0x5a54, 0x6a37, 0x7a16, 0xaf1, 0x1ad0, 0x2ab3, 0x3a92,
        0xfd2e, 0xed0f, 0xdd6c, 0xcd4d, 0xbdaa, 0xad8b, 0x9de8, 0x8dc9,
        0x7c26, 0x6c07, 0x5c64, 0x4c45, 0x3ca2, 0x2c83, 0x1ce0, 0xcc1,
        0xef1f, 0xff3e, 0xcf5d, 0xdf7c, 0xaf9b, 0xbfba, 0x8fd9, 0x9ff8,
        0x6e17, 0x7e36, 0x4e55, 0x5e74, 0x2e93, 0x3eb2, 0xed1, 0x1ef0,
    )

    @staticmethod
    def get(data):
        """
        return CRC calc value from raw serial data
        """
        crc = 0
        for byte in array('B', data):
            crc = (VProCRC.CRC_TABLE[(crc >> 8) ^ byte] ^ ((crc & 0xFF) << 8))
        return crc

    @staticmethod
    def verify(data):
        """
        perform CRC check on raw serial data, return true if valid.
        a valid CRC == 0.
        """
        if len(data) == 0:
            return False
        crc = VProCRC.get(data)
        if crc:
            log.info("CRC Bad")
        else:
            log.debug("CRC OK")
        return not crc


# --------------------------------------------------------------------------- #

class LoopStruct(Struct):
    """
    For unpacking data structure returned by the 'LOOP' command. this structure
    contains all the real-time data that can be read from the Davis Vantage Pro.
    """
    FMT = (
        ('LOO', '3s'), ('BarTrend', 'B'), ('PacketType', 'B'),
        ('NextRec', 'H'), ('Pressure', 'H'), ('TempIn', 'H'),
        ('HumIn', 'B'), ('TempOut', 'H'), ('WindSpeed', 'B'),
        ('WindSpeed10Min', 'B'), ('WindDir', 'H'), ('ExtraTemps', '7s'),
        ('SoilTemps', '4s'), ('LeafTemps', '4s'), ('HumOut', 'B'),
        ('HumExtra', '7s'), ('RainRate', 'H'), ('UV', 'B'),
        ('SolarRad', 'H'), ('RainStorm', 'H'), ('StormStartDate', 'H'),
        ('RainDay', 'H'), ('RainMonth', 'H'), ('RainYear', 'H'),
        ('ETDay', 'H'), ('ETMonth', 'H'), ('ETYear', 'H'),
        ('SoilMoist', '4s'), ('LeafWetness', '4s'), ('AlarmIn', 'B'),
        ('AlarmRain', 'B'), ('AlarmOut', '2s'), ('AlarmExTempHum', '8s'),
        ('AlarmSoilLeaf', '4s'), ('BatteryStatus', 'B'), ('BatteryVolts', 'H'),
        ('ForecastIcon', 'B'), ('ForecastRuleNo', 'B'), ('SunRise', 'H'),
        ('SunSet', 'H'), ('EOL', '2s'), ('CRC', 'H'),
    )

    def __init__(self):
        super(LoopStruct, self).__init__(self.FMT, '=')

    def _post_unpack(self, items):
        items['Pressure'] = items['Pressure'] / 1000.0
        items['TempIn'] = items['TempIn'] / 10.0
        items['TempOut'] = items['TempOut'] / 10.0
        items['RainRate'] = items['RainRate'] / 100.0
        items['RainStorm'] = items['RainStorm'] / 100.0
        items['StormStartDate'] = self._unpack_storm_date(items['StormStartDate'])
        # rain totals
        items['RainDay'] = items['RainDay'] / 100.0
        items['RainMonth'] = items['RainMonth'] / 100.0
        items['RainYear'] = items['RainYear'] / 100.0
        # evapotranspiration totals
        items['ETDay'] = items['ETDay'] / 1000.0
        items['ETMonth'] = items['ETMonth'] / 100.0
        items['ETYear'] = items['ETYear'] / 100.0
        # soil moisture + leaf wetness
        items['SoilMoist'] = struct.unpack('4B', items['SoilMoist'])
        items['LeafWetness'] = struct.unpack('4B', items['LeafWetness'])
        # battery statistics
        items['BatteryVolts'] = items['BatteryVolts'] * 300 / 512.0 / 100.0
        # sunrise / sunset
        items['SunRise'] = self._unpack_time(items['SunRise'])
        items['SunSet'] = self._unpack_time(items['SunSet'])
        return items

    @staticmethod
    def _unpack_time(val):
        """
        given a packed time field, unpack and return "HH:MM" string.
        """
        # format: HHMM, and space padded on the left.ex: "601" is 6:01 AM
        return "%02d:%02d" % divmod(val, 100)  # covert to "06:01"

    @staticmethod
    def _unpack_storm_date(date):
        """
        given a packed storm date field, unpack and return 'YYYY-MM-DD' string.
        """
        year = (date & 0x7f) + 2000  # 7 bits
        day = (date >> 7) & 0x01f  # 5 bits
        month = (date >> 12) & 0x0f  # 4 bits
        return "%s-%s-%s" % (year, month, day)


# --------------------------------------------------------------------------- #

class _ArchiveStruct(object):
    """
    common features for both Rev.A and Rev.B structures.
    """
    FMT = None

    def __init__(self):
        super(_ArchiveStruct, self).__init__(self.FMT, '=')

    def _post_unpack(self, items):
        vals = self._unpack_date_time(items['DateStamp'], items['TimeStamp'])
        items.update(zip(('Year', 'Month', 'Day', 'Hour', 'Min'), vals))
        items['TempOut'] = items['TempOut'] / 10.0
        items['TempOutHi'] = items['TempOutHi'] / 10.0
        items['TempOutLow'] = items['TempOutLow'] / 10.0
        items['Barometer'] = items['Barometer'] / 1000.0
        items['TempIn'] = items['TempIn'] / 10.0
        items['UV'] = items['UV'] / 10.0
        items['UVHi'] = items['UVHi'] / 10.0
        items['ETHour'] = items['ETHour'] / 1000.0
        items['SoilTemps'] = tuple(
            t - 90 for t in struct.unpack('4B', items['SoilTemps']))
        items['ExtraHum'] = struct.unpack('2B', items['ExtraHum'])
        items['SoilMoist'] = struct.unpack('4B', items['SoilMoist'])
        return items

    @staticmethod
    def _unpack_date_time(date, time_):
        day = date & 0x1f  # 5 bits
        month = (date >> 5) & 0x0f  # 4 bits
        year = ((date >> 9) & 0x7f) + 2000  # 7 bits
        hour, min_ = divmod(time_, 100)
        return year, month, day, hour, min_


# --------------------------------------------------------------------------- #

class _ArchiveAStruct(_ArchiveStruct, Struct):
    FMT = (
        ('DateStamp', 'H'), ('TimeStamp', 'H'), ('TempOut', 'H'),
        ('TempOutHi', 'H'), ('TempOutLow', 'H'), ('RainRate', 'H'),
        ('RainRateHi', 'H'), ('Pressure', 'H'), ('SolarRad', 'H'),
        ('WindSamps', 'H'), ('TempIn', 'H'), ('HumIn', 'B'),
        ('HumOut', 'B'), ('WindAvg', 'B'), ('WindHi', 'B'),
        ('WindHiDir', 'B'), ('WindAvgDir', 'B'), ('UV', 'B'),
        ('ETHour', 'B'), ('unused', 'B'), ('SoilMoist', '4s'),
        ('SoilTemps', '4s'), ('LeafWetness', '4s'), ('ExtraTemps', '2s'),
        ('ExtraHum', '2s'), ('ReedClosed', 'H'), ('ReedOpened', 'H'),
        ('unused', 'B'),
    )

    def _post_unpack(self, items):
        items = super(_ArchiveAStruct, self)._post_unpack(items)
        items['LeafWetness'] = struct.unpack('4B', items['LeafWetness'])
        items['ExtraTemps'] = tuple(
            t - 90 for t in struct.unpack('2B', items['ExtraTemps']))
        return items


# --------------------------------------------------------------------------- #

class _ArchiveBStruct(_ArchiveStruct, Struct):
    """
    This represents the structure of the Archive Packet (RevB) returned by the station with the DMPAFT command
    """
    FMT = (
        # These 16 bits hold the date that the archive was written in the following format:
        # Year (7 bits) | Month (4 bits) | Day (5 bits) or: day + month*32 + (year-2000)*512)
        ('DateStamp', 'H'),
        # Time on the Vantage that the archive record was
        # written:
        # (Hour * 100) + minute.
        ('TimeStamp', 'H'),
        # Either the Average Outside Temperature, or the
        # Final Outside Temperature over the archive period.
        # Units are (F / 10)
        ('TempOut', 'H'),
        # Highest Outside Temp over the archive period.
        ('TempOutHi', 'H'),
        # Lowest Outside Temp over the archive period.
        ('TempOutLow', 'H'),
        # Number of rain clicks over the archive period
        ('RainRate', 'H'),
        # Highest rain rate over the archive period, or the rate
        # shown on the console at the end of the period if there
        # was no rain. Units are (rain clicks / hour)
        ('RainRateHi', 'H'),
        # Barometer reading at the end of the archive period.
        # Units are (in Hg / 1000).
        ('Barometer', 'H'),
        # Average Solar Rad over the archive period.
        # Units are (Watts / m 2 )
        ('SolarRad', 'H'),
        # Number of packets containing wind speed data
        # received from the ISS or wireless anemometer.
        ('WindSamps', 'H'),
        # Either the Average Inside Temperature, or the Final
        # Inside Temperature over the archive period. Units
        # are (F / 10)
        ('TempIn', 'H'),
        # Inside Humidity at the end of the archive period
        ('HumIn', 'B'),
        # Outside Humidity at the end of the archive period
        ('HumOut', 'B'),
        # Average Wind Speed over the archive interval. Units are (MPH)
        ('WindAvg', 'B'),
        # Highest Wind Speed over the archive interval. Units are (MPH)
        ('WindHi', 'B'),
        # Direction code of the High Wind speed. 0 = N, 1 = NNE, 2 = NE, ... 14 = NW, 15 = NNW, 255 = Dashed
        ('WindHiDir', 'B'),
        # Prevailing or Dominant Wind Direction code.
        # 0 = N, 1 = NNE, 2 = NE, ... 14 = NW, 15 = NNW, 255 = Dashed
        # Firmware before July 8th 2001 does not report direction code 255
        ('WindAvgDir', 'B'),
        # Average UV Index. Units are (UV Index / 10)
        ('UV', 'B'),
        # ET accumulated over the last hour. Only records "on the hour" will have a non-zero value. Units are (in /1000)
        ('ETHour', 'B'),
        # Highest Solar Rad's value over the archive period. Units are (Watts / m 2)
        ('SolarRadHi', 'H'),
        # Highest UV Index value over the archive period.
        ('UVHi', 'B'),
        # Weather forecast rule at the end of the archive period.
        ('ForecastRuleNo', 'B'),
        # 2 Leaf Temperature values. Units are (F + 90)
        ('LeafTemps', '2s'),
        # 2 Leaf Wetness values. Range is 0-15
        ('LeafWetness', '2s'),
        # 4 Soil Temperatures. Units are (F + 90)
        ('SoilTemps', '4s'),
        # 0xFF = Rev A, 0x00 = Rev B archive record
        ('RecType', 'B'),
        # 2 Extra Humidity values
        ('ExtraHum', '2s'),
        # 3 Extra Temperature values. Units are (F + 90)
        ('ExtraTemps', '3s'),
        # 4 Soil Moisture values. Units are (cb)
        ('SoilMoist', '4s'),
    )

    def _post_unpack(self, items):
        items = super(_ArchiveBStruct, self)._post_unpack(items)
        items['LeafTemps'] = tuple(
            t - 90 for t in struct.unpack('2B', items['LeafTemps']))
        items['LeafWetness'] = struct.unpack('2B', items['LeafWetness'])
        items['ExtraTemps'] = tuple(
            t - 90 for t in struct.unpack('3B', items['ExtraTemps']))
        return items


# --------------------------------------------------------------------------- #

# simple data structures
DmpStruct = Struct(
    (('Pages', 'H'), ('Offset', 'H'), ('CRC', 'H')),
    order='=')

DmpPageStruct = Struct(
    (('Index', 'B'), ('Records', '260s'), ('unused', '4B'), ('CRC', 'H')),
    order='=')


class _TimeStruct(Struct):
    FMT = (
        ('Sec', 'B'),
        ('Min', 'B'),
        ('Hour', 'B'),
        ('Day', 'B'),
        ('Month', 'B'),
        ('Year', 'B'),
        ('CRC', 'H'),
    )

    def __init__(self):
        super(_TimeStruct, self).__init__(self.FMT, '=')

    def _post_unpack(self, items):
        items['Year'] = items['Year'] + 1900
        return items


# init structure classes
LoopStruct = LoopStruct()
ArchiveAStruct = _ArchiveAStruct()
ArchiveBStruct = _ArchiveBStruct()
timeStruct = _TimeStruct()


##############################################################################
# |--------------------------------------------------------------------------|#
# |--------------------------------------------------------------------------|#
# |                     API for the Davis Vantage Pro                        |#
# |--------------------------------------------------------------------------|#
# |--------------------------------------------------------------------------|#
##############################################################################

class VantagePro(Station):
    """
    A class capable of reading raw (binary) weather data from a
    vantage pro console and parsing it into usable scalar
    (integer/long/real) values.

    The data read from the console is in binary format. The data is in
    least-ordered nybble strategy, and must be read with correct sizes and
    offsets for proper byte ordering.
    """

    # device reply commands
    WAKE_ACK = '\n\r'.encode()
    ACK = '\x06'.encode()
    ESC = '\x1b'
    OK = '\n\rOK\n\r'

    # archive format type, unknown
    _ARCHIVE_REV_B = None

    def __init__(
            self,
            device,
            log_interval=5,
            log_start_date=None,
            clear=False,
            want_archives=True
    ):
        """
        Initialize the serial connection with the console.
        :param device: a "device" object that can do async read/write
        :param log_interval: default 5
        :param log_start_date: the datetime.datetime object representing the
            starting log date. Default None aka "all"
        :param clear: boolean, if true clean all the log in the console.
            Default False.
        :param want_archives: boolean, if true request and parse old archived
            entries from weather station. This is like 'clear' but without
            altering what is stored on the weather station. Default True
        """
        self.port = device
        # set the logging interval to be downloaded. Default all
        if log_start_date is None:
            self._archive_time = (0, 0)
        else:
            self._archive_time = (self.calcDateStamp(log_start_date),
                                  self.calcTimeStamp(log_start_date))

        if clear:
            self._cmd('CLRLOG')  # prevent getting a full log dump at startup
        self._cmd('SETPER', log_interval, ok=True)

        self.want_archives = want_archives

        self.fields = {}

    @staticmethod
    def calcDateStamp(date):
        """
        As stated into the Vantage Serial Protocol manual, this method converts
        a datetime object into the right DateStamp

        :param date: the datetime object to convert
        :return: the dateStamp integer
        """
        return date.day + date.month * 32 + (date.year - 2000) * 512

    @staticmethod
    def calcTimeStamp(date):
        """
        As stated into the Vantage Serial Protocol manual, this method converts
        a datetime object into the right TimeStamp.

        :param date: the datetime object to convert
        :return: the timeStamp integer
        """
        return 100 * date.hour + date.minute

    def __del__(self):
        """
        close serial port when object is deleted.
        """
        self.port.close()

    def _use_rev_b_archive(self, records, offset):
        """
        return True if weather station returns Rev.B archives
        """
        # if pre-determined, return result
        if type(self._ARCHIVE_REV_B) is bool:
            return self._ARCHIVE_REV_B
        # assume, B and check 'RecType' field
        data = ArchiveBStruct.unpack_from(records, offset)
        if data['RecType'] == 0:
            log.info('detected archive rev. B')
            self._ARCHIVE_REV_B = True
        else:
            log.info('detected archive rev. A')
            self._ARCHIVE_REV_B = False

        return self._ARCHIVE_REV_B

    async def _wakeup(self) -> None:
        """
        issue wakeup command to device to take out of standby mode.
        """
        awake, i = False, 0
        while not awake and i < 3:
            log.debug("send: WAKEUP")
            try:
                await self.port.write("\n".encode())
                ack = await asyncio.wait_for(
                        self.port.read(len(self.WAKE_ACK)),
                        timeout=1.2
                        )
                if ack == self.WAKE_ACK:
                    awake = True
            except asyncio.exceptions.TimeoutError:
                i += 1

        try:
            assert awake is True
        except AssertionError:
            raise NoDeviceException('Can not access weather station')

        return None

    async def _cmd(self, cmd, *args, **kw) -> None:
        """
        write a single command, with variable number of arguments. after the
        command, the device must return ACK
        """
        ok = kw.setdefault('ok', False)

        await self._wakeup()
        if args:
            cmd = "%s %s" % (cmd, ' '.join(str(a) for a in args))
        for i in range(3):
            log.debug("send: " + cmd)
            await self.port.write(f"{cmd} \n".encode())
            if ok:
                log.debug("expecting OK rather than ACK in reponse to cmd")
                try:
                    ack = await asyncio.wait_for(
                            self.port.read(len(self.OK)),  # read OK
                            timeout=5
                            )
                except asyncio.exceptions.TimeoutError:
                    raise NoDeviceException('Lost connection')

                # log_raw('read', ack)
                if ack == self.OK:
                    return
            else:
                try:
                    ack = await asyncio.wait_for(
                        self.port.read(len(self.ACK)),  # read ACK
                        timeout=1.2
                        )
                except asyncio.exceptions.TimeoutError:
                    raise NoDeviceException('Lost connection')

                # log_raw('read', ack)
                if ack == self.ACK:
                    return
        # raise NoDeviceException('Can not access weather station')

    async def _loop_cmd(self):
        """
        Reads a raw string containing data read from the device
        provided (in /dev/XXX) format. All reads are non-blocking.
        """
        await self._cmd('LOOP', 1)
        raw = await self.port.read(LoopStruct.size)  # read data
        return raw

    async def _dmpaft_cmd(self, time_fields):
        """
        issue a command to read the archive records after a known time stamp.
        """
        records = []
        # convert time stamp fields to buffer
        tbuf = struct.pack('2H', *time_fields)

        # 1. send 'DMPAFT' cmd
        await self._cmd('DMPAFT')

        # 2. send time stamp + crc
        crc = VProCRC.get(tbuf)
        crc = struct.pack('>H', crc)  # crc in big-endian format
        await self.port.write(tbuf + crc)  # send time stamp + crc
        ack = await self.port.read(len(self.ACK))  # read ACK
        if ack != self.ACK:
            return None  # if bad ack, return None

        # 3. read pre-amble data
        raw = await self.port.read(DmpStruct.size)
        if not VProCRC.verify(raw):  # check CRC value
            await self.port.write(self.ESC)  # if bad, escape and abort
            return
        await self.port.write(self.ACK)  # send ACK

        # 4. loop through all page records
        dmp = DmpStruct.unpack(raw)
        log.info('reading %d pages, start offset %d' %
                 (dmp['Pages'], dmp['Offset']))
        for i in range(dmp['Pages']):
            # 5. read page data
            raw = await self.port.read(DmpPageStruct.size)
            if not VProCRC.verify(raw):  # check CRC value
                await self.port.write(self.ESC)  # if bad, escape and abort
                return
            await self.port.write(self.ACK)  # send ACK

            # 6. loop through archive records
            page = DmpPageStruct.unpack(raw)
            offset = 0  # assume offset at 0
            if i == 0:
                offset = dmp['Offset'] * ArchiveAStruct.size
            while offset < ArchiveAStruct.size * 5:
                log.info('page %d, reading record at offset %d' %
                         (page['Index'], offset))
                if self._use_rev_b_archive(page['Records'], offset):
                    a = ArchiveBStruct.unpack_from(page['Records'], offset)
                else:
                    a = ArchiveAStruct.unpack_from(page['Records'], offset)
                # 7. verify that record has valid data, and store
                if a['DateStamp'] != 0xffff and a['TimeStamp'] != 0xffff:
                    records.append(a)
                offset += ArchiveAStruct.size
        log.info('read all pages')
        return records

    async def _get_loop_fields(self):
        crc_ok = None
        for i in range(3):
            raw = await self._loop_cmd()  # read raw data
            crc_ok = VProCRC.verify(raw)
            if crc_ok:
                break  # exit loop if valid
            time.sleep(1)

        if not crc_ok:
            raise NoDeviceException('Can not access weather station')

        return LoopStruct.unpack(raw)

    async def _get_new_archive_fields(self):
        """
        returns a dictionary of fields from the newest archive record in the
        device. return None when no records are new.
        """
        records = []
        for i in range(3):
            records = await self._dmpaft_cmd(self._archive_time)
            if records is not None:
                break
            time.sleep(1)

        if records is None:
            raise NoNewRecordsException('Can not download any new record.')

        # find the newest record
        new_rec = None
        for r in records:
            new_time = (r['DateStamp'], r['TimeStamp'])
            if self._archive_time < new_time:
                self._archive_time = new_time
                new_rec = r

        return new_rec

    @staticmethod
    def _calc_derived_fields(fields):
        """
        calculates the derived fields (those fields that are calculated)
        """
        # convenience variables for the calculations below
        temp_ = fields['TempOut']
        hum = fields['HumOut']
        wind_ = fields['WindSpeed']
        wind10min = fields['WindSpeed10Min']
        fields['HeatIndex'] = calc_heat_index(temp_, hum)
        fields['WindChill'] = calc_wind_chill(temp_, wind_, wind10min)
        fields['DewPoint'] = calc_dewpoint(temp_, hum)
        # store current data string
        now = time.localtime()
        fields['DateStamp'] = time.strftime("%Y-%m-%d %H:%M:%S", now)
        fields['Year'] = now[0]
        fields['Month'] = str(now[1]).zfill(2)
        now = time.gmtime()
        fields['DateStampUtc'] = time.strftime("%Y-%m-%d %H:%M:%S", now)
        fields['YearUtc'] = now[0]
        fields['MonthUtc'] = str(now[1]).zfill(2)

    async def parse(self):
        """
        read and parse a set of data read from the console.  after the
        data is parsed it is available in the fields variable.
        """
        fields = await self._get_loop_fields()
        # TODO: this will overwrite the last archived record with the newest record.
        # Is this the expected behavior?
        if self.want_archives:
            fields['Archive'] = await self._get_new_archive_fields()

        self._calc_derived_fields(fields)

        # set the fields variable the values in the dict
        self.fields = fields

    async def get_reading(self) -> WeatherPoint:
        """Return a single weather reading."""
        await self.parse()

        return self._fields_to_weather_point(self.fields)

    @staticmethod
    def _fields_to_weather_point(fields: dict) -> WeatherPoint:
        """Convert VantagePro fields dictionary to WeatherPoint.

        Only supports limited subset of data available in self.fields -
        generally only those useful for posting to weather services.
        """
        return WeatherPoint(
            temperature_f=fields['TempOut'],
            pressure=fields['Pressure'],
            dew_point_f=fields['DewPoint'],
            humidity=fields['HumOut'],
            rain_rate_in=fields['RainRate'],
            rain_day_in=fields['RainDay'],
            time=dt.datetime.strptime(fields['DateStampUtc'], "%Y-%m-%d %H:%M:%S"),
            wind_speed_mph=fields['WindSpeed10Min'],
            wind_direction=fields['WindDir'],
        )
