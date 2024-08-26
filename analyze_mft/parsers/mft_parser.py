import asyncio
import logging
from tqdm import tqdm

from typing import Dict, Any, Optional
from analyze_mft.utilities.mft_record import MFTRecord
from analyze_mft.parsers.attribute_parser import AttributeParser
from analyze_mft.constants.constants import *
from analyze_mft.utilities.windows_time import WindowsTime

class MFTParser:
    def __init__(self, options: Any, file_handler: Any, csv_writer: Any, json_writer: Any, thread_manager: Any):
        self.options = options
        self.file_handler = file_handler
        self.csv_writer = csv_writer
        self.json_writer = json_writer
        self.thread_manager = thread_manager
        self.logger = logging.getLogger('analyzeMFT')
        self.mft: Dict[int, Dict[str, Any]] = {}
        self.num_records = 0

    async def parse_mft_file(self):
        if self.options.output:
            await self.csv_writer.write_csv_header()

        total_size = await self.file_handler.get_file_size()
        processed_size = 0
        record_count = 0
        max_records = 1000000  # Safeguard: maximum number of records to process

        try:
            with tqdm(total=total_size, unit='B', unit_scale=True, desc="Parsing MFT") as pbar:
                while processed_size < total_size and record_count < max_records:
                    raw_record = await self.file_handler.read_mft_record()
                    if not raw_record:
                        self.logger.info("Reached end of file")
                        break

                    processed_size += len(raw_record)
                    record_count += 1

                    await self._process_record(raw_record, record_count)
                    pbar.update(len(raw_record))

                    if record_count % 1000 == 0:
                        self.logger.info(f"Processed {record_count} records, {processed_size/total_size:.2%} complete")
                        await asyncio.sleep(0)  # Allow other tasks to run

        except asyncio.CancelledError:
            self.logger.warning("Parsing was cancelled. Saving progress...")
        finally:
            self.logger.info(f"Total records processed: {self.num_records}")
            await self.generate_filepaths()
            if self.options.jsonfile:
                await self.json_writer.write_json_file()

        self.logger.info("MFT parsing completed or interrupted.")

    async def _process_record(self, raw_record: bytes, record_count: int):
        try:
            if len(raw_record) != 1024:
                self.logger.warning(f"Unexpected record size: {len(raw_record)} bytes")
                if len(raw_record) < 42:
                    self.logger.error("Record too small to be valid. Skipping.")
                    return

            self.logger.debug(f"Processing record {record_count}")

            record = await self._parse_single_record(raw_record)
            if record:
                self.mft[self.num_records] = record
                if self.options.output:
                    await self.csv_writer.write_csv_record(record)
                if self.options.jsonfile:
                    await self.json_writer.write_json_record(record)
                self.num_records += 1

        except Exception as e:
            self.logger.error(f"Error processing record {record_count}: {str(e)}")
            self.logger.error(f"Raw record data: {raw_record.hex()[:100]}...")  # Log first 100 bytes of the record

    async def _parse_single_record(self, raw_record: bytes) -> Optional[Dict[str, Any]]:
        try:
            mft_record = MFTRecord(raw_record, self.options)
            parsed_record = await mft_record.parse()

            if not parsed_record:
                self.logger.warning(f"Failed to parse record at offset {self.file_handler.file_mft.tell() - len(raw_record)}")
                return None

            record = {
                'recordnum': parsed_record.get('recordnum', 0),
                'seq': parsed_record.get('seq', 0),
                'flags': parsed_record.get('flags', 0),
                'filename': '',
                'fncnt': 0,
                'notes': ''
            }

            self.logger.debug(f"Parsed record header: {record}")
            self.logger.debug(f"Raw record (first 64 bytes): {raw_record[:64].hex()}")

            if 'attributes' not in parsed_record or not parsed_record['attributes']:
                self.logger.warning(f"No attributes found in record {record['recordnum']}. Raw data: {raw_record[:128].hex()}")
                return record

            attribute_parser = AttributeParser(raw_record, self.options)

            for attr_type, attr_data in parsed_record['attributes'].items():
                await self._parse_attribute(record, attr_type, attr_data, attribute_parser)

            await self._check_usec_zero(record)
            return record
        except Exception as e:
            self.logger.error(f"Unhandled exception in _parse_single_record: {str(e)}")
            return None

    async def _parse_attribute(self, record: Dict[str, Any], attr_type: int, attr_data: bytes, attribute_parser: AttributeParser):
        self.logger.debug(f"Parsing attribute type {attr_type}")
        attr_header = await attribute_parser.parse_attribute_header()
        if not attr_header:
            self.logger.warning(f"Failed to parse attribute header for type {attr_type}")
            return

        content_offset = attr_header.get('content_offset')
        if content_offset is None:
            content_offset = attr_header.get('data_runs_offset', 0)

        try:
            if attr_type == STANDARD_INFORMATION:
                record['si'] = await attribute_parser.parse_standard_information(content_offset)
            elif attr_type == FILE_NAME:
                fn = await attribute_parser.parse_file_name(content_offset)
                if fn:
                    record[f'fn{record["fncnt"]}'] = fn
                    record['fncnt'] += 1
                    if record['fncnt'] == 1:
                        record['filename'] = fn['name']
            elif attr_type == OBJECT_ID:
                record['objid'] = await attribute_parser.parse_object_id(content_offset)
            elif attr_type == DATA:
                record['data'] = True
            elif attr_type == INDEX_ROOT:
                record['indexroot'] = True
            elif attr_type == INDEX_ALLOCATION:
                record['indexallocation'] = True
            elif attr_type == BITMAP:
                record['bitmap'] = True
            elif attr_type == LOGGED_UTILITY_STREAM:
                record['loggedutility'] = True
        except Exception as e:
            self.logger.error(f"Error parsing attribute {attr_type}: {str(e)}")
            record['notes'] += f"Error parsing attribute {attr_type}: {str(e)} | "

    async def _check_usec_zero(self, record: Dict[str, Any]):
        if 'si' in record:
            si_times = [record['si'][key] for key in ['crtime', 'mtime', 'atime', 'ctime']]
            record['usec-zero'] = all(isinstance(time, WindowsTime) and time.unixtime % 1 == 0 for time in si_times)

    async def generate_filepaths(self):
        for i in self.mft:
            if self.mft[i]['filename'] == '':
                if self.mft[i]['fncnt'] > 0:
                    self.mft[i]['filename'] = await self.get_folder_path(i)  
                else:
                    self.mft[i]['filename'] = 'NoFNRecord'

    async def get_folder_path(self, seqnum: int, visited: Optional[set] = None) -> str:
        if visited is None:
            visited = set()
        
        if seqnum in visited:
            return 'Circular_Reference'
        
        visited.add(seqnum)
        
        if seqnum not in self.mft:
            return 'Orphan'

        if self.mft[seqnum]['filename'] != '':
            return self.mft[seqnum]['filename']

        try:
            if self.mft[seqnum]['fn0']['parent_ref'] == 5:
                self.mft[seqnum]['filename'] = '/' + self.mft[seqnum][f'fn{self.mft[seqnum]["fncnt"] - 1}']['name']
                return self.mft[seqnum]['filename']
        except KeyError:
            self.mft[seqnum]['filename'] = 'NoFNRecord'
            return self.mft[seqnum]['filename']

        if self.mft[seqnum]['fn0']['parent_ref'] == seqnum:
            self.mft[seqnum]['filename'] = f"ORPHAN/{self.mft[seqnum][f'fn{self.mft[seqnum]["fncnt"] - 1}']['name']}"
            return self.mft[seqnum]['filename']

        parentpath = await self.get_folder_path(self.mft[seqnum]['fn0']['parent_ref'], visited)
        self.mft[seqnum]['filename'] = f"{parentpath}/{self.mft[seqnum][f'fn{self.mft[seqnum]["fncnt"] - 1}']['name']}"

        return self.mft[seqnum]['filename']