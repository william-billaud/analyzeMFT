import struct
import logging
from .windows_time import WindowsTime


class AttributeParser:
    def __init__(self, raw_data, options):

        if not raw_data:
            self.logger.warning("No raw data provided to AttributeParser")

        if not options:
            self.logger.warning("No options provided to AttributeParser")

        self.raw_data = raw_data
        self.options = options
        self.logger = logging.getLogger('analyzeMFT')


    def parse(self):

        if len(self.raw_data) < 4:  
        
            self.logger.warning("Insufficient data for parsing attribute")
            return None
        
        return self.decode_attribute_header()

    def decode_attribute_header(self):
        
        if len(self.raw_data) < 24:
            if len(self.raw_data) < 4:
                self.logger.warning("Insufficient data for parsing attribute")
            d = {'type': struct.unpack("<I", self.raw_data[:4])[0]}
            if d['type'] == 0xffffffff:
                return d
            self.logger.warning("Insufficient data for full attribute header")
    
        d = {}
        d['type'] = struct.unpack("<I", self.raw_data[:4])[0]
            
        d['len'] = struct.unpack("<I", self.raw_data[4:8])[0]
        d['res'] = struct.unpack("B", self.raw_data[8:9])[0]
        d['name_off'] = struct.unpack("<H", self.raw_data[10:12])[0]
        d['flags'] = struct.unpack("<H", self.raw_data[12:14])[0]
        d['id'] = struct.unpack("<H", self.raw_data[14:16])[0]
        
        if d['res'] == 0:
            d['ssize'] = struct.unpack("<L", self.raw_data[16:20])[0]
            d['soff'] = struct.unpack("<H", self.raw_data[20:22])[0]
            d['idxflag'] = struct.unpack("<H", self.raw_data[22:24])[0]
        
        else:
            if len(self.raw_data) < 64:
                self.logger.warning("Insufficient data for non-resident attribute")

            d['start_vcn'] = struct.unpack("<Q", self.raw_data[16:24])[0]
            d['last_vcn'] = struct.unpack("<Q", self.raw_data[24:32])[0]
            d['run_off'] = struct.unpack("<H", self.raw_data[32:34])[0]
            d['compusize'] = struct.unpack("<H", self.raw_data[34:36])[0]
            d['f1'] = struct.unpack("<I", self.raw_data[36:40])[0]
            d['alen'] = struct.unpack("<Q", self.raw_data[40:48])[0]
            d['ssize'] = struct.unpack("<Q", self.raw_data[48:56])[0]
            d['initsize'] = struct.unpack("<Q", self.raw_data[56:64])[0]

        return d

    def parse_standard_information(self):

        header = self.decode_attribute_header()
        if not header or 'soff' not in header:
            self.logger.warning("Invalid attribute header for standard information")
            return None
        
        s = self.raw_data[header['soff']:]

        if len(s) < 72:
            self.logger.warning("Insufficient data for parsing standard information")
            return None

        d = {}

        d['crtime'] = WindowsTime(struct.unpack("<Q", s[:8])[0], self.options.localtz)
        d['mtime'] = WindowsTime(struct.unpack("<Q", s[8:16])[0], self.options.localtz)
        d['ctime'] = WindowsTime(struct.unpack("<Q", s[16:24])[0], self.options.localtz)
        d['atime'] = WindowsTime(struct.unpack("<Q", s[24:32])[0], self.options.localtz)
        d['dos'] = struct.unpack("<I", s[32:36])[0]
        d['maxver'] = struct.unpack("<I", s[36:40])[0]
        d['ver'] = struct.unpack("<I", s[40:44])[0]
        d['class_id'] = struct.unpack("<I", s[44:48])[0]
        d['own_id'] = struct.unpack("<I", s[48:52])[0]
        d['sec_id'] = struct.unpack("<I", s[52:56])[0]
        d['quota'] = struct.unpack("<Q", s[56:64])[0]
        d['usn'] = struct.unpack("<Q", s[64:72])[0]

        self.logger.debug(f"Creation timestamp: {d['crtime'].timestamp()}")
        return d

    def parse_file_name(self, record):

        header = self.decode_attribute_header()
        if not header or 'soff' not in header:
            self.logger.warning("Invalid attribute header for standard information")
            return None
        
        
        s = self.raw_data[header['soff']:]
        if len(s) < 66:
            self.logger.warning("Insufficient data for parsing file name")
        try:
            windows_time = WindowsTime(timestamp, self.options.localtz)
        except ValueError as e:
            self.logger.warning(f"Invalid timestamp encountered: {e}")
            windows_time = WindowsTime(0, self.options.localtz)  

        d = {}
        d['par_ref'] = struct.unpack("<Q", s[:8])[0]
        d['crtime'] = WindowsTime(struct.unpack("<Q", s[:8])[0], self.options.localtz)
        d['mtime'] = WindowsTime(struct.unpack("<Q", s[8:16])[0], self.options.localtz)
        d['ctime'] = WindowsTime(struct.unpack("<Q", s[16:24])[0], self.options.localtz)
        d['atime'] = WindowsTime(struct.unpack("<Q", s[24:32])[0], self.options.localtz)
        d['alloc_fsize'] = struct.unpack("<Q", s[40:48])[0]
        d['real_fsize'] = struct.unpack("<Q", s[48:56])[0]
        d['flags'] = struct.unpack("<I", s[56:60])[0]
        d['nlen'] = struct.unpack("B", s[64:65])[0]
        d['nspace'] = struct.unpack("B", s[65:66])[0]

        bytes_left = d['nlen']*2
        if len(s) < 66 + bytes_left:
            self.logger.warning("Insufficient data for filename")
        d['name'] = s[66:66+bytes_left].decode('utf-16-le')

        self.logger.debug(f"Parsed FN timestamps: crtime={d['crtime']}, mtime={d['mtime']}, atime={d['atime']}, ctime={d['ctime']}")
        
        return d