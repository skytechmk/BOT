#!/usr/bin/env python3
"""
Long Term Memory System for S.P.E.C.T.R.E.
Uses SQLite FTS5 extension to keep a searchable episodic memory and core beliefs.
"""
import sqlite3
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class LongTermMemory:
    def __init__(self, db_path="performance_logs/spectre_memory.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Table for rigid rules and preferences
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS core_beliefs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        topic TEXT UNIQUE,
                        fact TEXT,
                        updated_at TIMESTAMP
                    )
                ''')
                
                # FTS5 Virtual Table for searchable context/conversation
                # Catch exceptions if FTS5 is not compiled in this sqlite binary (rare on modern systems, but safe to check)
                try:
                    cursor.execute('''
                        CREATE VIRTUAL TABLE IF NOT EXISTS episodic_memory USING fts5(
                            event, timestamp
                        )
                    ''')
                except sqlite3.OperationalError as e:
                    logger.error(f"FTS5 not available: {e}. Falling back to standard table.")
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS episodic_memory (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            event TEXT,
                            timestamp TEXT
                        )
                    ''')

                conn.commit()
                logger.info("🧠 Long-Term Memory SQLite Initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize memory DB: {e}")

    def store_core_belief(self, topic, fact):
        """Store an overriding rule or preference (overwrites if topic exists)"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO core_beliefs (topic, fact, updated_at) 
                    VALUES (?, ?, ?)
                    ON CONFLICT(topic) DO UPDATE SET 
                        fact=excluded.fact, 
                        updated_at=excluded.updated_at
                ''', (topic, fact, datetime.now().isoformat()))
                conn.commit()
            return {"success": True, "message": f"Core belief updated for '{topic}'."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def store_memory(self, event):
        """Append a generic memory or conversation snippet"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO episodic_memory (event, timestamp) 
                    VALUES (?, ?)
                ''', (event, datetime.now().isoformat()))
                conn.commit()
            return {"success": True, "message": "Memory stored."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def recall_core_beliefs(self):
        """Retrieve all core beliefs"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT topic, fact FROM core_beliefs')
                rows = cursor.fetchall()
                beliefs = {row['topic']: row['fact'] for row in rows}
            return {"success": True, "beliefs": beliefs}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def recall_memory(self, query, limit=5):
        """Semantically retrieve relevant memories using Full-Text Search"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # To make MATCH work on standard tables (if FTS fallback triggered), handle it dynamically
                # Let's try FTS5 MATCH first
                try:
                    # Clean up query to avoid sqlite FTS parse errors (remove quotes, brackets etc)
                    safe_query = "".join(c for c in query if c.isalnum() or c.isspace())
                    safe_query = safe_query.strip()
                    if not safe_query:
                        return {"success": True, "memories": []}
                        
                    # Prefix search using *
                    fts_query = f"\"{safe_query}\"*" if len(safe_query.split()) == 1 else safe_query
                    
                    cursor.execute('''
                        SELECT event, timestamp FROM episodic_memory 
                        WHERE episodic_memory MATCH ? 
                        ORDER BY rank LIMIT ?
                    ''', (fts_query, limit))
                except sqlite3.OperationalError:
                    # Fallback to standard LIKE if MATCH fails or standard table was used
                    cursor.execute('''
                        SELECT event, timestamp FROM episodic_memory 
                        WHERE event LIKE ? 
                        ORDER BY timestamp DESC LIMIT ?
                    ''', (f"%{query}%", limit))

                rows = cursor.fetchall()
                memories = [{"event": row['event'], "date": row['timestamp']} for row in rows]
                
            return {"success": True, "query": query, "results": memories}
        except Exception as e:
            return {"success": False, "error": str(e)}

# Singleton instance
SPECTRE_MEMORY = LongTermMemory()

# MCP Async Wrappers
async def store_core_belief(topic, fact):
    return json.dumps(SPECTRE_MEMORY.store_core_belief(topic, fact), indent=2)

async def recall_core_beliefs():
    return json.dumps(SPECTRE_MEMORY.recall_core_beliefs(), indent=2)

async def store_memory(event):
    return json.dumps(SPECTRE_MEMORY.store_memory(event), indent=2)

async def recall_memory(query):
    return json.dumps(SPECTRE_MEMORY.recall_memory(query), indent=2)

if __name__ == "__main__":
    import asyncio
    async def testing():
        print(await store_core_belief("auto_healer", "Be completely autonomous and document changes."))
        print(await store_memory("The user prefers high-parameter AI models like 405B over 8B variants."))
        print(await recall_core_beliefs())
        print(await recall_memory("models"))
    asyncio.run(testing())
