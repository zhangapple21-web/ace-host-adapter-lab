"""Configuration management for ACE Bridge."""
from __future__ import annotations
import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BridgeConfig:
    """Centralized configuration with environment variable and JSON file support."""
    
    # 核心路径
    ace_root: Path = field(default_factory=lambda: Path(os.environ.get("ACE_BRIDGE_ROOT", r"C:\tmp\ace_core")).resolve())
    python: Path = field(default_factory=lambda: Path(os.environ.get("ACE_BRIDGE_PYTHON", r"C:\tmp\ace-host-adapter-lab\.venv\Scripts\python.exe")))
    
    # 协议
    protocol: str = "ace.host_adapter.v0"
    
    # 限制
    max_snapshot_size: int = 1024 * 1024  # 1 MiB
    cli_timeout: int = 60  # seconds
    default_limit: int = 20
    max_limit: int = 100
    query_max_len: int = 256
    reason_max_len: int = 500
    request_id_max_len: int = 128
    host_id_max_len: int = 128
    
    # 速率限制
    enable_rate_limit: bool = False
    max_rps_per_host: float = 10.0
    burst_per_host: int = 20
    
    # 日志
    log_level: str = os.environ.get("ACE_BRIDGE_LOG_LEVEL", "INFO")
    
    # 健康检查
    health_check_enabled: bool = True
    
    # 指标
    metrics_enabled: bool = False
    metrics_port: int = 9090
    
    # 缓存
    cache_ttl_seconds: float = 5.0
    cache_max_entries: int = 100
    
    def __post_init__(self):
        """Validate and normalize paths."""
        self.ace_root = self.ace_root.resolve()
        self.python = self.python.resolve()
    
    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "BridgeConfig":
        """Load config from JSON file (optional) + environment variables."""
        config = cls()
        
        # 从 JSON 文件加载（环境变量优先）
        if config_path is None:
            config_path = Path(os.environ.get("ACE_BRIDGE_CONFIG", "")) or (config.ace_root / "ace_bridge_config.json")
        
        if config_path and config_path.is_file():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                # 只更新已定义的字段
                for key, value in data.items():
                    if hasattr(config, key):
                        if key in ("ace_root", "python") and isinstance(value, str):
                            setattr(config, key, Path(value).resolve())
                        else:
                            setattr(config, key, value)
            except (json.JSONDecodeError, OSError):
                pass  # 忽略配置文件错误，使用默认值+环境变量
        
        return config
    
    def to_dict(self) -> dict:
        """Serialize to dict for logging/debugging."""
        return {k: str(v) if isinstance(v, Path) else v for k, v in self.__dict__.items()}


# 全局配置实例（延迟加载）
_config: Optional[BridgeConfig] = None


def get_config() -> BridgeConfig:
    """Get global config instance (singleton)."""
    global _config
    if _config is None:
        _config = BridgeConfig.load()
    return _config


def reload_config(config_path: Optional[Path] = None) -> BridgeConfig:
    """Force reload configuration."""
    global _config
    _config = BridgeConfig.load(config_path)
    return _config