"""
数据库模块 — MySQL → SQLite → 无DB 三级回退。
"""
import json
from datetime import datetime

DB_ENABLED = False  # 是否成功连接了数据库
DB_TYPE = "sqlite"
DB_PATH = "db.sqlite3"
MYSQL_CONFIG = None


def _connect():
    """获取数据库连接"""
    if DB_TYPE == "mysql":
        import pymysql
        conn = pymysql.connect(
            host=MYSQL_CONFIG.get("host", "localhost"),
            port=MYSQL_CONFIG.get("port", 3306),
            user=MYSQL_CONFIG.get("user", "root"),
            password=MYSQL_CONFIG.get("password", ""),
            database=MYSQL_CONFIG.get("database", "ai_grader"),
            charset="utf8mb4",
            autocommit=True,
        )
        return conn, "%s"
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        return conn, "?"


def init_db(config: dict):
    """初始化数据库，MySQL不可用则回退SQLite，都不行就仅Excel"""
    global DB_ENABLED, DB_TYPE, DB_PATH, MYSQL_CONFIG

    DB_TYPE = config.get("type", "sqlite")
    MYSQL_CONFIG = config.get("mysql", {}) if DB_TYPE == "mysql" else None
    DB_PATH = config.get("sqlite_path", "db.sqlite3")

    # ---- 尝试 MySQL ----
    if DB_TYPE == "mysql":
        try:
            import pymysql
            conn = pymysql.connect(
                host=MYSQL_CONFIG.get("host", "localhost"),
                port=MYSQL_CONFIG.get("port", 3306),
                user=MYSQL_CONFIG.get("user", "root"),
                password=MYSQL_CONFIG.get("password", ""),
                database=MYSQL_CONFIG.get("database", "ai_grader"),
                charset="utf8mb4",
                autocommit=True,
            )
            _create_tables(conn, "mysql")
            conn.close()
            DB_ENABLED = True
            print(f"  [DB] MySQL 连接成功 ({MYSQL_CONFIG.get('host')}:{MYSQL_CONFIG.get('port')}/{MYSQL_CONFIG.get('database')})")
            return
        except Exception as e:
            print(f"  [DB] MySQL 连接失败: {e}")
            print(f"  [DB] 回退到 SQLite ...")

    # ---- 尝试 SQLite ----
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        _create_tables(conn, "sqlite")
        conn.close()
        DB_ENABLED = True
        DB_TYPE = "sqlite"
        print(f"  [DB] SQLite 就绪 ({DB_PATH})")
    except Exception as e:
        print(f"  [DB] SQLite 不可用: {e}")
        print(f"  [DB] 数据库已禁用，仅输出 Excel")
        DB_ENABLED = False


def _create_tables(conn, db_kind: str):
    """建表"""
    c = conn.cursor()
    auto = "AUTO_INCREMENT" if db_kind == "mysql" else "AUTOINCREMENT"
    txt = "TEXT" if db_kind == "mysql" else "TEXT"

    c.execute(f"""CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY {auto},
        student_id VARCHAR(64) NOT NULL,
        student_name VARCHAR(64) NOT NULL,
        class_name VARCHAR(128) DEFAULT '',
        file_name VARCHAR(256) NOT NULL,
        total_score REAL DEFAULT 0,
        grade VARCHAR(16) DEFAULT '',
        status VARCHAR(32) DEFAULT 'pending',
        comment VARCHAR(512) DEFAULT '',
        graded_at VARCHAR(64) DEFAULT '',
        raw_data {txt} DEFAULT ''
    )""")

    c.execute(f"""CREATE TABLE IF NOT EXISTS scores (
        id INTEGER PRIMARY KEY {auto},
        paper_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        question_name VARCHAR(64) NOT NULL,
        criterion_id VARCHAR(16) NOT NULL,
        criterion_name VARCHAR(64) NOT NULL,
        score REAL DEFAULT 0,
        max_score REAL DEFAULT 0,
        reason VARCHAR(256) DEFAULT ''
    )""")

    c.execute(f"""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY {auto},
        paper_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        model VARCHAR(64) NOT NULL,
        prompt_hash VARCHAR(32) DEFAULT '',
        tokens_input INTEGER DEFAULT 0,
        tokens_output INTEGER DEFAULT 0,
        raw_response {txt} DEFAULT '',
        created_at VARCHAR(64) DEFAULT ''
    )""")

    conn.commit()


# ======== 下面是写/查操作，全部带 DB_ENABLED 守卫 ========

def _guard():
    if not DB_ENABLED:
        return None, None
    return _connect()


def save_paper(student_id: str, student_name: str, class_name: str,
               file_name: str, raw_data: dict) -> int | None:
    conn, ph = _guard()
    if not conn:
        return None
    c = conn.cursor()
    c.execute(f"INSERT INTO papers (student_id, student_name, class_name, file_name, raw_data) VALUES ({ph}, {ph}, {ph}, {ph}, {ph})",
              (student_id, student_name, class_name, file_name, json.dumps(raw_data, ensure_ascii=False)))
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid


def save_score(paper_id: int | None, question_id: int, question_name: str,
               criterion_id: str, criterion_name: str,
               score: float, max_score: float, reason: str = ""):
    if not DB_ENABLED or paper_id is None:
        return
    conn, ph = _connect()
    c = conn.cursor()
    c.execute(f"INSERT INTO scores (paper_id, question_id, question_name, criterion_id, criterion_name, score, max_score, reason) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
              (paper_id, question_id, question_name, criterion_id, criterion_name, score, max_score, reason))
    conn.commit()
    conn.close()


def update_paper(paper_id: int | None, total_score: float, status: str = "done", comment: str = ""):
    if not DB_ENABLED or paper_id is None:
        return
    conn, ph = _connect()
    c = conn.cursor()
    c.execute(f"UPDATE papers SET total_score={ph}, status={ph}, comment={ph}, graded_at={ph} WHERE id={ph}",
              (total_score, status, comment, datetime.now().isoformat(), paper_id))
    conn.commit()
    conn.close()


def save_audit(paper_id: int | None, question_id: int, model: str,
               tokens_input: int, tokens_output: int, raw_response: str):
    if not DB_ENABLED or paper_id is None:
        return
    conn, ph = _connect()
    c = conn.cursor()
    c.execute(f"INSERT INTO audit_log (paper_id, question_id, model, tokens_input, tokens_output, raw_response, created_at) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
              (paper_id, question_id, model, tokens_input, tokens_output, raw_response, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_all_results() -> list:
    conn, _ = _guard()
    if not conn:
        return []
    c = conn.cursor()
    c.execute("SELECT * FROM papers WHERE status='done' ORDER BY class_name, student_id")
    rows = []
    for r in c.fetchall():
        d = {}
        for i, col in enumerate(c.description):
            d[col[0]] = r[i]
        rows.append(d)
    conn.close()
    return rows


def get_question_scores(paper_id: int) -> dict:
    """获取某试卷各题总分，返回 {qid: score}"""
    conn, _ = _guard()
    if not conn:
        return {}
    c = conn.cursor()
    c.execute("SELECT question_id, SUM(score) FROM scores WHERE paper_id=? GROUP BY question_id", (paper_id,))
    result = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return result


def get_statistics() -> dict:
    conn, _ = _guard()
    if not conn:
        return {}
    c = conn.cursor()
    c.execute("SELECT COUNT(*), AVG(total_score), MAX(total_score), MIN(total_score) FROM papers WHERE status='done'")
    row = c.fetchone()
    count, avg_s, max_s, min_s = (row[0] or 0), (row[1] or 0), (row[2] or 0), (row[3] or 0)

    c.execute("""SELECT
        SUM(CASE WHEN total_score >= 90 THEN 1 ELSE 0 END),
        SUM(CASE WHEN total_score >= 80 AND total_score < 90 THEN 1 ELSE 0 END),
        SUM(CASE WHEN total_score >= 70 AND total_score < 80 THEN 1 ELSE 0 END),
        SUM(CASE WHEN total_score >= 60 AND total_score < 70 THEN 1 ELSE 0 END),
        SUM(CASE WHEN total_score < 60 THEN 1 ELSE 0 END)
        FROM papers WHERE status='done'""")
    bands = list(c.fetchone())

    c.execute("SELECT SUM(tokens_input), SUM(tokens_output) FROM audit_log")
    tok_in, tok_out = c.fetchone()

    conn.close()
    return {
        "total": count or 0,
        "avg_score": round(avg_s, 1) if avg_s else 0,
        "max_score": max_s or 0,
        "min_score": min_s or 0,
        "bands": {"90+": bands[0] or 0, "80-89": bands[1] or 0, "70-79": bands[2] or 0, "60-69": bands[3] or 0, "<60": bands[4] or 0},
        "tokens_input": tok_in or 0,
        "tokens_output": tok_out or 0,
    }
