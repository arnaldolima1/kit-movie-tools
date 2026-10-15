"""ISO 9660: just enough to walk the directories of a PSP disc image."""
import struct

SECTOR = 2048


class Iso:
    def __init__(self, path):
        self.path = path
        self.file = open(path, 'rb')
        pvd = self.read(16 * SECTOR, SECTOR)
        if pvd[1:6] != b'CD001':
            self.file.close()
            raise ValueError(f'{path}: not an ISO 9660 disc image')
        self.root = self._record(pvd[156:190])

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def read(self, offset, size):
        self.file.seek(offset)
        return self.file.read(size)

    def game_id(self):
        """The disc's game id (UMD_DATA.BIN starts with it), e.g. UCES-01401."""
        for entry in self.entries(self.root):
            if entry['name'].upper() == 'UMD_DATA.BIN':
                return self.read(entry['lba'] * SECTOR, 10).split(b'|')[0].decode('ascii', 'replace')
        return None

    @staticmethod
    def _record(data):
        lba = struct.unpack_from('<I', data, 2)[0]
        size = struct.unpack_from('<I', data, 10)[0]
        name = data[33:33 + data[32]]
        return {'lba': lba, 'size': size, 'dir': bool(data[25] & 2), 'name': name}

    def entries(self, directory):
        data = self.read(directory['lba'] * SECTOR, (directory['size'] + SECTOR - 1) // SECTOR * SECTOR)
        at = 0
        while at < len(data):
            length = data[at]
            if length == 0:  # records do not cross sectors: the rest is padding
                at = (at // SECTOR + 1) * SECTOR
                continue
            entry = self._record(data[at:at + length])
            at += length
            if entry['name'] in (b'\x00', b'\x01'):
                continue
            entry['name'] = entry['name'].decode('ascii', 'replace').split(';')[0]
            yield entry

    def walk(self, directory=None, path=''):
        for entry in self.entries(directory or self.root):
            full = f"{path}/{entry['name']}"
            if entry['dir']:
                yield from self.walk(entry, full)
            else:
                yield full, entry
