"""
utils.py 测试 —— 工具函数
覆盖：密码哈希、用户管理、配置加载、运行时配置构建
"""
import os
import json
import pytest
from unittest.mock import patch

from src.utils import (
    hpw, load_users, verify_user, save_user,
    load_teacher, load_config, load_rubric,
    _ensure_users_file, DEFAULT_PASSWORD_HASH,
)


class TestPasswordHash:
    """密码哈希"""

    def test_hash_stability(self):
        """相同密码哈希一致"""
        assert hpw("admin123") == hpw("admin123")

    def test_hash_different(self):
        """不同密码哈希不同"""
        assert hpw("admin123") != hpw("admin456")

    def test_hash_length(self):
        """SHA-256 = 64 hex chars"""
        assert len(hpw("test")) == 64

    def test_default_password_hash(self):
        """默认密码哈希应该是有效的 SHA-256"""
        assert len(DEFAULT_PASSWORD_HASH) == 64
        # admin123 的 SHA-256
        assert hpw("admin123") == DEFAULT_PASSWORD_HASH


class TestUserManagement:
    """用户管理"""

    def test_ensure_users_file_creates(self, tmp_dir):
        """首次运行创建 users.json"""
        users_path = os.path.join(tmp_dir, "users.json")

        # 确保文件不存在
        if os.path.exists(users_path):
            os.remove(users_path)

        with patch('src.utils.USERS_PATH', users_path):
            _ensure_users_file()
            assert os.path.exists(users_path)

            with open(users_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            assert "admin" in data
            assert data["admin"]["role"] == "admin"

    def test_load_users(self, tmp_dir):
        """读取用户"""
        users_path = os.path.join(tmp_dir, "users.json")
        test_data = {
            "admin": {
                "password_hash": "abc123",
                "display_name": "admin",
                "role": "admin",
            },
            "teacher1": {
                "password_hash": "def456",
                "display_name": "张老师",
                "role": "teacher",
            },
        }
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)

        with patch('src.utils.USERS_PATH', users_path):
            users = load_users()
            assert "admin" in users
            assert "teacher1" in users
            assert users["teacher1"]["display_name"] == "张老师"

    def test_verify_user_correct(self, tmp_dir):
        """正确密码验证通过"""
        users_path = os.path.join(tmp_dir, "users.json")
        test_data = {
            "admin": {
                "password_hash": hpw("admin123"),
                "display_name": "管理员",
                "role": "admin",
            },
        }
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)

        with patch('src.utils.USERS_PATH', users_path):
            result = verify_user("admin", "admin123")
            assert result is not None
            display_name, role = result
            assert display_name == "管理员"
            assert role == "admin"

    def test_verify_user_wrong_password(self, tmp_dir):
        """错误密码验证失败"""
        users_path = os.path.join(tmp_dir, "users.json")
        test_data = {
            "admin": {
                "password_hash": hpw("admin123"),
                "display_name": "admin",
                "role": "admin",
            },
        }
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)

        with patch('src.utils.USERS_PATH', users_path):
            result = verify_user("admin", "wrong_password")
            assert result is None

    def test_verify_user_not_found(self, tmp_dir):
        """用户不存在"""
        users_path = os.path.join(tmp_dir, "users.json")
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        with patch('src.utils.USERS_PATH', users_path):
            result = verify_user("nonexistent", "password")
            assert result is None

    def test_save_user_new(self, tmp_dir):
        """新增用户"""
        users_path = os.path.join(tmp_dir, "users.json")
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        with patch('src.utils.USERS_PATH', users_path):
            save_user("new_teacher", "pass123", "新老师", "teacher")

            users = load_users()
            assert "new_teacher" in users
            assert users["new_teacher"]["display_name"] == "新老师"
            assert users["new_teacher"]["role"] == "teacher"
            assert users["new_teacher"]["password_hash"] == hpw("pass123")

    def test_save_user_update(self, tmp_dir):
        """更新已有用户"""
        users_path = os.path.join(tmp_dir, "users.json")
        test_data = {
            "teacher1": {
                "password_hash": hpw("old_pass"),
                "display_name": "旧名字",
                "role": "teacher",
            },
        }
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)

        with patch('src.utils.USERS_PATH', users_path):
            save_user("teacher1", "new_pass", "新名字", "admin")

            users = load_users()
            assert users["teacher1"]["display_name"] == "新名字"
            assert users["teacher1"]["role"] == "admin"
            assert users["teacher1"]["password_hash"] == hpw("new_pass")


class TestLoadTeacher:
    """兼容旧接口"""

    def test_load_first_admin(self, tmp_dir):
        """取第一个 admin 用户"""
        users_path = os.path.join(tmp_dir, "users.json")
        test_data = {
            "user1": {"role": "teacher", "display_name": "教师1", "password_hash": "x"},
            "admin1": {"role": "admin", "display_name": "管理员", "password_hash": "hash1"},
            "admin2": {"role": "admin", "display_name": "管理员2", "password_hash": "hash2"},
        }
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)

        with patch('src.utils.USERS_PATH', users_path):
            pwd_hash, name = load_teacher()
            assert pwd_hash == "hash1"
            assert name == "管理员"

    def test_load_teacher_fallback(self, tmp_dir):
        """无 admin 时 fallback"""
        users_path = os.path.join(tmp_dir, "users.json")
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        with patch('src.utils.USERS_PATH', users_path):
            pwd_hash, name = load_teacher()
            assert pwd_hash == DEFAULT_PASSWORD_HASH
            assert name == "教师"


class TestLoadConfig:
    """配置加载"""

    def test_load_config(self, tmp_dir):
        """从 YAML 加载配置"""
        import yaml
        config_path = os.path.join(tmp_dir, "config.yaml")
        config_data = {
            "llm": {"provider": "deepseek", "model": "deepseek-chat"},
            "grading": {"mode": "normal"},
        }
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f)

        cfg = load_config(config_path)
        assert cfg["llm"]["provider"] == "deepseek"
        assert cfg["grading"]["mode"] == "normal"


class TestLoadRubric:
    """评分标准加载"""

    def test_load_rubric(self, tmp_dir):
        """从 JSON 加载评分标准"""
        rubric_path = os.path.join(tmp_dir, "rubric.json")
        rubric_data = {
            "exam": {"name": "测试考试", "total_score": 100},
            "questions": [],
        }
        with open(rubric_path, 'w', encoding='utf-8') as f:
            json.dump(rubric_data, f, ensure_ascii=False)

        rubric = load_rubric(rubric_path)
        assert rubric["exam"]["name"] == "测试考试"
