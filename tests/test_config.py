"""
配置管理单元测试

覆盖 backend/config.py 的核心方法：
- Config.__init__() — 默认配置加载
- _load_from_env() — 环境变量加载
- load_yaml() — YAML 配置加载
- update() — 动态更新配置
- to_dict() — 序列化
- get_exchange_fee() — 手续费查询
"""

import os

import pytest
import yaml

from backend.config import (
    DEFAULT_CONFIG,
    DEFAULT_SYMBOLS,
    SUPPORTED_EXCHANGES,
    Config,
)


# ----------------------------------------------------------------------------
# __init__() 默认配置加载测试
# ----------------------------------------------------------------------------
class TestConfigInit:
    """Config.__init__() 默认配置加载测试"""

    def test_default_config_values(self):
        """默认配置值正确"""
        config = Config()
        assert config.model.min_profitability == DEFAULT_CONFIG["min_profitability"]
        assert config.model.order_amount == DEFAULT_CONFIG["order_amount"]
        assert config.model.scan_interval == DEFAULT_CONFIG["scan_interval"]
        assert config.model.max_order_age == DEFAULT_CONFIG["max_order_age"]
        assert config.model.paper_trade == DEFAULT_CONFIG["paper_trade"]
        assert config.model.fee_rate == DEFAULT_CONFIG["fee_rate"]
        assert config.model.top_n_opportunities == DEFAULT_CONFIG["top_n_opportunities"]

    def test_default_exchanges(self):
        """默认启用所有支持的交易所"""
        config = Config()
        assert config.model.exchanges == SUPPORTED_EXCHANGES

    def test_default_symbols(self):
        """默认监控交易对列表正确"""
        config = Config()
        assert config.model.symbols == DEFAULT_SYMBOLS
        assert len(config.model.symbols) == 20

    def test_default_exchange_fees_initialized(self):
        """所有交易所手续费率初始化为默认费率"""
        config = Config()
        for ex in SUPPORTED_EXCHANGES:
            assert ex in config.model.exchange_fees
            assert config.model.exchange_fees[ex] == config.model.fee_rate

    def test_api_keys_empty_by_default(self):
        """默认无 API 密钥"""
        config = Config()
        assert config.api_keys == {}


# ----------------------------------------------------------------------------
# _load_from_env() 环境变量加载测试
# ----------------------------------------------------------------------------
class TestLoadFromEnv:
    """_load_from_env() 环境变量加载测试"""

    def test_load_min_profitability(self, monkeypatch):
        """MIN_PROFITABILITY 环境变量覆盖默认值"""
        monkeypatch.setenv("MIN_PROFITABILITY", "0.005")
        config = Config()
        assert config.model.min_profitability == 0.005

    def test_load_order_amount(self, monkeypatch):
        """ORDER_AMOUNT 环境变量覆盖默认值"""
        monkeypatch.setenv("ORDER_AMOUNT", "0.1")
        config = Config()
        assert config.model.order_amount == 0.1

    def test_load_scan_interval(self, monkeypatch):
        """SCAN_INTERVAL 环境变量覆盖默认值"""
        monkeypatch.setenv("SCAN_INTERVAL", "30")
        config = Config()
        assert config.model.scan_interval == 30

    def test_load_max_order_age(self, monkeypatch):
        """MAX_ORDER_AGE 环境变量覆盖默认值"""
        monkeypatch.setenv("MAX_ORDER_AGE", "300")
        config = Config()
        assert config.model.max_order_age == 300

    def test_load_paper_trade_true(self, monkeypatch):
        """PAPER_TRADE=true 启用模拟交易"""
        monkeypatch.setenv("PAPER_TRADE", "true")
        config = Config()
        assert config.model.paper_trade is True

    def test_load_paper_trade_false(self, monkeypatch):
        """PAPER_TRADE=false 禁用模拟交易"""
        monkeypatch.setenv("PAPER_TRADE", "false")
        config = Config()
        assert config.model.paper_trade is False

    def test_load_api_keys_from_env(self, monkeypatch):
        """从环境变量加载交易所 API 密钥"""
        monkeypatch.setenv("BINANCE_API_KEY", "binance_key_123")
        monkeypatch.setenv("BINANCE_API_SECRET", "binance_secret_456")
        config = Config()
        assert "binance" in config.api_keys
        assert config.api_keys["binance"]["apiKey"] == "binance_key_123"
        assert config.api_keys["binance"]["secret"] == "binance_secret_456"

    def test_load_api_keys_requires_both(self, monkeypatch):
        """API 密钥需要 key 和 secret 同时存在"""
        monkeypatch.setenv("BINANCE_API_KEY", "only_key")
        # 不设置 BINANCE_API_SECRET
        config = Config()
        assert "binance" not in config.api_keys

    def test_invalid_env_value_does_not_crash(self, monkeypatch):
        """无效环境变量值不导致崩溃（捕获异常）"""
        monkeypatch.setenv("MIN_PROFITABILITY", "not_a_number")
        # 不应抛异常，保留默认值
        config = Config()
        assert config.model.min_profitability == DEFAULT_CONFIG["min_profitability"]


# ----------------------------------------------------------------------------
# load_yaml() YAML 配置加载测试
# ----------------------------------------------------------------------------
class TestLoadYaml:
    """load_yaml() YAML 配置加载测试"""

    def test_load_yaml_overrides_defaults(self, tmp_yaml_config):
        """YAML 配置覆盖默认值"""
        with open(tmp_yaml_config, "w", encoding="utf-8") as f:
            yaml.dump({
                "min_profitability": 0.003,
                "order_amount": 0.05,
                "scan_interval": 15,
            }, f)
        config = Config(config_path=tmp_yaml_config)
        assert config.model.min_profitability == 0.003
        assert config.model.order_amount == 0.05
        assert config.model.scan_interval == 15

    def test_load_yaml_nonexistent_file(self):
        """不存在的 YAML 文件使用默认配置（不抛异常）"""
        config = Config(config_path="/nonexistent/path/config.yaml")
        assert config.model.min_profitability == DEFAULT_CONFIG["min_profitability"]

    def test_load_yaml_empty_file(self, tmp_yaml_config):
        """空 YAML 文件使用默认配置"""
        with open(tmp_yaml_config, "w", encoding="utf-8") as f:
            f.write("")
        config = Config(config_path=tmp_yaml_config)
        assert config.model.min_profitability == DEFAULT_CONFIG["min_profitability"]

    def test_load_yaml_null_content(self, tmp_yaml_config):
        """YAML 内容为 null 时使用默认配置"""
        with open(tmp_yaml_config, "w", encoding="utf-8") as f:
            f.write("null\n")
        config = Config(config_path=tmp_yaml_config)
        assert config.model.min_profitability == DEFAULT_CONFIG["min_profitability"]

    def test_load_yaml_invalid_syntax(self, tmp_yaml_config):
        """YAML 语法错误时不崩溃"""
        with open(tmp_yaml_config, "w", encoding="utf-8") as f:
            f.write("invalid: yaml: content: [unclosed\n")
        config = Config(config_path=tmp_yaml_config)
        # 解析失败，保留默认值
        assert config.model.min_profitability == DEFAULT_CONFIG["min_profitability"]

    def test_load_yaml_exchanges_filtered(self, tmp_yaml_config):
        """YAML 中的交易所列表会被过滤为受支持的交易所"""
        with open(tmp_yaml_config, "w", encoding="utf-8") as f:
            yaml.dump({"exchanges": ["binance", "unknown_exchange", "okx"]}, f)
        config = Config(config_path=tmp_yaml_config)
        assert "binance" in config.model.exchanges
        assert "okx" in config.model.exchanges
        assert "unknown_exchange" not in config.model.exchanges

    def test_load_yaml_api_keys(self, tmp_yaml_config):
        """从 YAML 加载 API 密钥"""
        with open(tmp_yaml_config, "w", encoding="utf-8") as f:
            yaml.dump({
                "api_keys": {
                    "binance": {"apiKey": "yaml_key", "secret": "yaml_secret"},
                },
            }, f)
        config = Config(config_path=tmp_yaml_config)
        assert config.api_keys["binance"]["apiKey"] == "yaml_key"
        assert config.api_keys["binance"]["secret"] == "yaml_secret"

    def test_load_yaml_exchange_fees(self, tmp_yaml_config):
        """从 YAML 加载交易所手续费覆盖"""
        with open(tmp_yaml_config, "w", encoding="utf-8") as f:
            yaml.dump({"exchange_fees": {"binance": 0.0005}}, f)
        config = Config(config_path=tmp_yaml_config)
        assert config.model.exchange_fees["binance"] == 0.0005


# ----------------------------------------------------------------------------
# update() 动态更新配置测试
# ----------------------------------------------------------------------------
class TestUpdateConfig:
    """update() 动态更新配置测试"""

    def test_update_min_profitability(self):
        """更新最小利润率"""
        config = Config()
        config.update({"min_profitability": 0.005})
        assert config.model.min_profitability == 0.005

    def test_update_order_amount(self):
        """更新下单量"""
        config = Config()
        config.update({"order_amount": 0.1})
        assert config.model.order_amount == 0.1

    def test_update_scan_interval(self):
        """更新扫描间隔"""
        config = Config()
        config.update({"scan_interval": 30})
        assert config.model.scan_interval == 30

    def test_update_max_order_age(self):
        """更新订单超时"""
        config = Config()
        config.update({"max_order_age": 300})
        assert config.model.max_order_age == 300

    def test_update_paper_trade(self):
        """更新模拟交易标志"""
        config = Config()
        config.update({"paper_trade": False})
        assert config.model.paper_trade is False

    def test_update_fee_rate(self):
        """更新默认手续费率"""
        config = Config()
        config.update({"fee_rate": 0.0005})
        assert config.model.fee_rate == 0.0005

    def test_update_top_n_opportunities(self):
        """更新最大机会数"""
        config = Config()
        config.update({"top_n_opportunities": 50})
        assert config.model.top_n_opportunities == 50

    def test_update_exchanges_filtered(self):
        """更新交易所列表时过滤不支持的交易所"""
        config = Config()
        config.update({"exchanges": ["binance", "fake_ex", "okx"]})
        assert "binance" in config.model.exchanges
        assert "okx" in config.model.exchanges
        assert "fake_ex" not in config.model.exchanges

    def test_update_exchanges_all_invalid_keeps_old(self):
        """所有交易所都不支持时保留原列表"""
        config = Config()
        original = config.model.exchanges.copy()
        config.update({"exchanges": ["fake1", "fake2"]})
        assert config.model.exchanges == original

    def test_update_symbols(self):
        """更新交易对列表"""
        config = Config()
        config.update({"symbols": ["BTC/USDT", "ETH/USDT"]})
        assert config.model.symbols == ["BTC/USDT", "ETH/USDT"]

    def test_update_exchange_fees_merged(self):
        """更新交易所手续费时合并而非覆盖"""
        config = Config()
        original_count = len(config.model.exchange_fees)
        config.update({"exchange_fees": {"binance": 0.0005}})
        assert config.model.exchange_fees["binance"] == 0.0005
        # 其他交易所手续费保留
        assert len(config.model.exchange_fees) == original_count

    def test_update_partial_only_provided_fields(self):
        """部分更新只修改提供的字段"""
        config = Config()
        original_scan = config.model.scan_interval
        config.update({"min_profitability": 0.005})
        # scan_interval 不应改变
        assert config.model.scan_interval == original_scan

    def test_update_invalid_value_does_not_crash(self):
        """无效值不导致崩溃"""
        config = Config()
        config.update({"min_profitability": "not_a_number"})
        # 捕获 ValueError，保留原值
        assert config.model.min_profitability == DEFAULT_CONFIG["min_profitability"]

    def test_update_api_keys(self):
        """通过 update 加载 API 密钥"""
        config = Config()
        config.update({
            "api_keys": {
                "binance": {"apiKey": "new_key", "secret": "new_secret"},
            },
        })
        assert config.api_keys["binance"]["apiKey"] == "new_key"


# ----------------------------------------------------------------------------
# to_dict() 序列化测试
# ----------------------------------------------------------------------------
class TestToDict:
    """to_dict() 序列化测试"""

    def test_to_dict_contains_all_fields(self):
        """to_dict 包含所有配置字段"""
        config = Config()
        data = config.to_dict()
        expected_keys = {
            "exchanges", "symbols", "min_profitability", "order_amount",
            "scan_interval", "max_order_age", "paper_trade", "fee_rate",
            "exchange_fees", "top_n_opportunities", "api_key_status",
        }
        assert expected_keys.issubset(set(data.keys()))

    def test_to_dict_no_api_key_plaintext(self):
        """to_dict 不暴露 API 密钥明文"""
        config = Config()
        config.api_keys["binance"] = {"apiKey": "secret_key_123", "secret": "secret_val"}
        data = config.to_dict()
        # 不应包含密钥明文
        assert "secret_key_123" not in str(data)
        assert "secret_val" not in str(data)
        # api_key_status 只包含布尔状态
        assert data["api_key_status"]["binance"] is True

    def test_to_dict_api_key_status_false_when_absent(self):
        """未配置密钥的交易所 api_key_status 为 False"""
        config = Config()
        data = config.to_dict()
        for ex in config.model.exchanges:
            assert data["api_key_status"][ex] is False

    def test_to_dict_reflects_updates(self):
        """to_dict 反映更新后的配置"""
        config = Config()
        config.update({"min_profitability": 0.005, "scan_interval": 30})
        data = config.to_dict()
        assert data["min_profitability"] == 0.005
        assert data["scan_interval"] == 30


# ----------------------------------------------------------------------------
# get_exchange_fee() 手续费查询测试
# ----------------------------------------------------------------------------
class TestGetExchangeFee:
    """get_exchange_fee() 手续费查询测试"""

    def test_get_fee_for_configured_exchange(self):
        """已配置交易所返回其手续费率"""
        config = Config()
        assert config.get_exchange_fee("binance") == config.model.fee_rate

    def test_get_fee_for_unconfigured_exchange(self):
        """未配置交易所返回默认费率"""
        config = Config()
        # 删除一个交易所的手续费配置
        del config.model.exchange_fees["binance"]
        assert config.get_exchange_fee("binance") == config.model.fee_rate

    def test_get_fee_after_update(self):
        """更新手续费后查询返回新值"""
        config = Config()
        config.update({"exchange_fees": {"binance": 0.0005}})
        assert config.get_exchange_fee("binance") == 0.0005

    def test_get_fee_custom_rate(self):
        """自定义手续费率查询"""
        config = Config()
        config.model.exchange_fees["okx"] = 0.0008
        assert config.get_exchange_fee("okx") == 0.0008
        # 其他交易所仍为默认
        assert config.get_exchange_fee("binance") == config.model.fee_rate
