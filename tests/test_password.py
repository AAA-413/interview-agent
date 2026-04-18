from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 测试密码
password = "admin123"
stored_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyRJH0Bg6S1u"

# 验证
result = pwd_context.verify(password, stored_hash)
print(f"Password: {password}")
print(f"Hash: {stored_hash}")
print(f"Verify result: {result}")

# 生成新的哈希
new_hash = pwd_context.hash(password)
print(f"\nNew hash for '{password}': {new_hash}")
print(f"Verify new hash: {pwd_context.verify(password, new_hash)}")
