# src/database/connection.py
import asyncpg
from src.core import config

# Biến toàn cục để giữ connection pool
# Global variable to hold the connection pool
_pool = None

async def get_pool():
    """
    Lấy connection pool hiện tại, nếu chưa có thì tạo mới.
    
    Returns:
        asyncpg.Pool: Đối tượng connection pool.
    """
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                dsn=config.DATABASE_URL,
                min_size=5,   # Số kết nối tối thiểu
                max_size=20,  # Số kết nối tối đa
                timeout=30,   # Timeout khi lấy kết nối
                command_timeout=5, # Timeout cho một câu lệnh
            )
            print("Đã tạo connection pool tới PostgreSQL thành công!")
        except Exception as e:
            print(f"Lỗi khi tạo connection pool: {e}")
            raise
    return _pool

async def close_pool():
    """
    Đóng connection pool nếu nó đang tồn tại.
    """
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        print("Đã đóng connection pool.")

class DatabaseConnection:
    """
    Một context manager để quản lý kết nối từ pool một cách an toàn.
    Sử dụng:
    async with DatabaseConnection() as conn:
        await conn.execute(...)
    """
    def __init__(self):
        self.pool = None
        self.conn = None

    async def __aenter__(self):
        self.pool = await get_pool()
        self.conn = await self.pool.acquire()
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            await self.pool.release(self.conn)
