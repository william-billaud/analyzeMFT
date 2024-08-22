from .common_imports import *


class MFTRecord:
    def __init__(self, raw_record, options):

        if not raw_record:
            raise ValueError("No raw record data provided to MFTRecord")
        if not options:
            raise ValueError("No options provided to MFTRecord")

        self.raw_record = raw_record
        self.options = options
        self.record = {
            'filename': '',
            'notes': '',
            'fncnt': 0,
            'objid': None,
            'volname': None,
            'volinfo': None,
            'data': None,
            'indexroot': None,
            'indexallocation': None,
            'bitmap': None,
            'reparse': None,
            'eainfo': None,
            'ea': None,
            'propertyset': None,
            'loggedutility': None,
            'stf-fn-shift': False,
            'usec-zero': False
        }
        self.read_ptr = 0

    def decode_mft_header(self):
        self.record['magic'] = struct.unpack("<I", self.raw_record[:4])[0]
        self.record['upd_off'] = struct.unpack("<H", self.raw_record[4:6])[0]
        self.record['upd_cnt'] = struct.unpack("<H", self.raw_record[6:8])[0]
        self.record['lsn'] = struct.unpack("<d", self.raw_record[8:16])[0]
        self.record['seq'] = struct.unpack("<H", self.raw_record[16:18])[0]
        self.record['link'] = struct.unpack("<H", self.raw_record[18:20])[0]
        self.record['attr_off'] = struct.unpack("<H", self.raw_record[20:22])[0]
        self.record['flags'] = struct.unpack("<H", self.raw_record[22:24])[0]
        self.record['size'] = struct.unpack("<I", self.raw_record[24:28])[0]
        self.record['alloc_sizef'] = struct.unpack("<I", self.raw_record[28:32])[0]
        self.record['base_ref'] = struct.unpack("<Lxx", self.raw_record[32:38])[0]
        self.record['base_seq'] = struct.unpack("<H", self.raw_record[38:40])[0]
        self.record['next_attrid'] = struct.unpack("<H", self.raw_record[40:42])[0]
        self.record['f1'] = self.raw_record[42:44]
        self.record['recordnum'] = struct.unpack("<I", self.raw_record[44:48])[0]

    def parse(self):

        if len(self.raw_record) < 48:  
            raise ValueError(f"Invalid MFT record size: Expected at least 48 bytes, got {len(self.raw_record)}")

        try:
            windows_time = WindowsTime(timestamp, self.options.localtz)
        except ValueError as e:
            self.logger.warning(f"Invalid timestamp encountered: {e}")
            windows_time = WindowsTime(0, self.options.localtz)  
            
        try:
            self.decode_mft_header()

            if self.record['attr_off'] >= len(self.raw_record):
                raise ValueError(f"Invalid attribute offset: {self.record['attr_off']} exceeds record length {len(self.raw_record)}")

            self.read_ptr = self.record['attr_off']
            
            while self.read_ptr < len(self.raw_record):

                if self.read_ptr + 8 > len(self.raw_record): 
                    break

                attr_parser = AttributeParser(self.raw_record[self.read_ptr:], self.options)
                attr_record = attr_parser.parse()
                
                if attr_record['type'] == 0xffffffff:
                    break

                if attr_record['type'] == 0x10: 
                    self.record['si'] = attr_parser.parse_standard_information()

                elif attr_record['type'] == 0x30: 
                    fn_record = attr_parser.parse_file_name(self.record)
                    self.record['fn', self.record['fncnt']] = fn_record
                    self.record['fncnt'] += 1

                if attr_record['len'] > 0:
                    self.read_ptr += attr_record['len']
                    
                else:
                    break

        except struct.error as e:
            print(f"StructError while parsing record: {e}")
            return None

        except Exception as e:
            print(f"Unexpected error while parsing record: {e}")
            return None

        return self.record