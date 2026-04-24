import os
import json
import sqlite3
import time
from datetime import datetime, timedelta
from utils_logger import log_message
import threading

class SignalRegistryDB:
    def __init__(self, db_path="signal_registry.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
        self.migrate_from_json("signal_registry.json")
    
    def get_conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
        
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Main signals table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                pair TEXT NOT NULL,
                signal TEXT NOT NULL,
                price REAL,
                confidence REAL,
                targets_json TEXT,
                stop_loss REAL,
                leverage INTEGER,
                features_json TEXT,
                timestamp REAL NOT NULL,
                status TEXT DEFAULT 'OPEN',
                telegram_message_id INTEGER,
                cornix_response_json TEXT,
                pnl REAL DEFAULT 0.0,
                closed_timestamp REAL
            )
        ''')
        
        # Archival table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS archived_signals (
                signal_id TEXT PRIMARY KEY,
                pair TEXT NOT NULL,
                signal TEXT NOT NULL,
                price REAL,
                confidence REAL,
                targets_json TEXT,
                stop_loss REAL,
                leverage INTEGER,
                features_json TEXT,
                timestamp REAL NOT NULL,
                status TEXT DEFAULT 'OPEN',
                telegram_message_id INTEGER,
                cornix_response_json TEXT,
                pnl REAL DEFAULT 0.0,
                closed_timestamp REAL
            )
        ''')
        
        # Migrations — add columns introduced after initial schema
        for tbl in ('signals', 'archived_signals'):
            try:
                cur.execute(f'ALTER TABLE {tbl} ADD COLUMN targets_hit TEXT DEFAULT "[]"')
            except Exception:
                pass  # column already exists

        # Indices
        cur.execute('CREATE INDEX IF NOT EXISTS idx_signals_pair ON signals(pair)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp)')
        
        conn.commit()
        conn.close()

    def migrate_from_json(self, json_path):
        if not os.path.exists(json_path) or os.path.exists(self.db_path + ".migrated"):
            return
            
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                
            conn = self.get_conn()
            cur = conn.cursor()
            
            count = 0
            for sig_id, metadata in data.items():
                cur.execute('''
                    INSERT OR IGNORE INTO signals 
                    (signal_id, pair, signal, price, confidence, targets_json, stop_loss, leverage, 
                     features_json, timestamp, status, telegram_message_id, pnl) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    sig_id,
                    metadata.get('pair', 'UNKNOWN'),
                    metadata.get('signal', 'NEUTRAL'),
                    metadata.get('price', 0.0),
                    metadata.get('confidence', 0.0),
                    json.dumps(metadata.get('targets', [])),
                    metadata.get('stop_loss', 0.0),
                    metadata.get('leverage', 1),
                    json.dumps(metadata.get('features', {})),
                    metadata.get('timestamp', time.time()),
                    metadata.get('status', 'OPEN'),
                    metadata.get('telegram_message_id'),
                    metadata.get('pnl', 0.0)
                ))
                count += 1
            
            conn.commit()
            
            # Prune immediately during migration
            self.prune_old_signals()
            
            open(self.db_path + ".migrated", 'w').close()
            log_message(f"Successfully migrated {count} signals to SQLite")
            
        except Exception as e:
            log_message(f"Error migrating from JSON: {e}")
            
    def prune_old_signals(self, days=30):
        try:
            conn = self.get_conn()
            cur = conn.cursor()
            cutoff = time.time() - (days * 86400)
            
            # Move to archive
            cur.execute('''
                INSERT OR IGNORE INTO archived_signals
                SELECT * FROM signals WHERE timestamp < ?
            ''', (cutoff,))
            
            # Delete from main
            cur.execute('DELETE FROM signals WHERE timestamp < ?', (cutoff,))
            conn.commit()
            
            if cur.rowcount > 0:
                log_message(f"Pruned {cur.rowcount} signals older than {days} days")
                
        except Exception as e:
            log_message(f"Error pruning signals: {e}")

    def get_signal(self, signal_id):
        try:
            cur = self.get_conn().cursor()
            cur.execute('SELECT * FROM signals WHERE signal_id = ?', (signal_id,))
            row = cur.fetchone()
            if row:
                return self._row_to_dict(row)
            return None
        except Exception as e:
            log_message(f"Error getting signal {signal_id}: {e}")
            return None
            
    def set_signal(self, signal_id, data):
        try:
            conn = self.get_conn()
            cur = conn.cursor()
            
            cur.execute('''
                INSERT OR REPLACE INTO signals 
                (signal_id, pair, signal, price, confidence, targets_json, stop_loss, leverage, 
                 features_json, timestamp, status, telegram_message_id, pnl) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal_id,
                data.get('pair', 'UNKNOWN'),
                data.get('signal', 'NEUTRAL'),
                data.get('price', 0.0),
                data.get('confidence', 0.0),
                json.dumps(data.get('targets', [])),
                data.get('stop_loss', 0.0),
                data.get('leverage', 1),
                json.dumps(data.get('features', {})),
                data.get('timestamp', time.time()),
                data.get('status', 'OPEN'),
                data.get('telegram_message_id'),
                data.get('pnl', 0.0)
            ))
            conn.commit()
        except Exception as e:
            log_message(f"Error saving signal {signal_id}: {e}")

    def update_signal(self, signal_id, updates):
        current = self.get_signal(signal_id)
        if current:
            current.update(updates)
            self.set_signal(signal_id, current)
            
    def get_all(self):
        try:
            cur = self.get_conn().cursor()
            cur.execute('SELECT * FROM signals')
            result = {}
            for row in cur.fetchall():
                result[row['signal_id']] = self._row_to_dict(row)
            return result
        except Exception as e:
            log_message(f"Error getting all signals: {e}")
            return {}

    def _row_to_dict(self, row):
        d = dict(row)
        if 'targets_json' in d and d['targets_json']:
            d['targets'] = json.loads(d['targets_json'])
        if 'features_json' in d and d['features_json']:
            d['features'] = json.loads(d['features_json'])
        # Normalise targets_hit: old schema stored INTEGER (0/1/2), new stores JSON list
        th = d.get('targets_hit', [])
        if isinstance(th, int):
            d['targets_hit'] = list(range(1, th + 1)) if th > 0 else []
        elif isinstance(th, str):
            try:
                d['targets_hit'] = json.loads(th)
            except Exception:
                d['targets_hit'] = []
        elif not isinstance(th, list):
            d['targets_hit'] = []
        return d

# Dictionary-like wrapper to match existing interface
class SignalRegistryProxy:
    def __init__(self, db: SignalRegistryDB):
        self.db = db
        
    def __getitem__(self, key):
        val = self.db.get_signal(key)
        if val is None:
            raise KeyError(key)
        return val
        
    def __setitem__(self, key, value):
        self.db.set_signal(key, value)
        
    def __contains__(self, key):
        return self.db.get_signal(key) is not None
        
    def __delitem__(self, key):
        # We don't delete, we just mark as closed usually, but if called:
        pass
        
    def __len__(self):
        cur = self.db.get_conn().cursor()
        cur.execute('SELECT count(*) FROM signals')
        return cur.fetchone()[0]
        
    def get(self, key, default=None):
        val = self.db.get_signal(key)
        return val if val is not None else default
        
    def items(self):
        all_data = self.db.get_all()
        return all_data.items()
        
    def values(self):
        all_data = self.db.get_all()
        return all_data.values()
        
    def keys(self):
        all_data = self.db.get_all()
        return all_data.keys()
        
    def pop(self, key, default=None):
        val = self.db.get_signal(key)
        if val is not None:
             # Just return it, standard dict pop deletes but here we don't really want to delete
             return val
        return default
        
    def update(self, other_dict):
        for k, v in other_dict.items():
            self[k] = v
