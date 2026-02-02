#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Union

from parser import parse
from semant import SemanticAnalyzer

try:
    from code_generator import CodeGenerator
except ImportError:
    CodeGenerator = None
    print("警告: 未找到 code_generator 模块，编译功能将无法生成指令。")


class DatapackWriter:
    # MC版本与pack_format映射表
    VERSION_TO_PACK_FORMAT = {
        "1.21.4": 61, "1.21.3": 57, "1.21.2": 57, "1.21.1": 48, "1.21": 48,
        "1.20.6": 41, "1.20.5": 41, "1.20.4": 26, "1.20.3": 26, "1.20.2": 18,
        "1.20.1": 15, "1.20": 15, "1.19.4": 12, "1.19.3": 12, "1.19": 10,
    }

    # 1.21+ 单数化映射表 (复数 -> 单数)
    SINGULAR_MAPPINGS = {
        'functions': 'function',
        'loot_tables': 'loot_table',
        'recipes': 'recipe',
        'advancements': 'advancement',
        'structures': 'structure',
        'predicates': 'predicate',
        'items': 'item',
        'blocks': 'block',
        'entities': 'entity',
        'fluids': 'fluid',
        'game_events': 'game_event',
    }

    def __init__(self,
                 output_path: Union[str, Path],
                 config: Optional[Dict[str, Any]] = None):
        self.output_path = Path(output_path).resolve()
        self.config = config or {}

        # 基础配置
        self.namespace = self.config.get("namespace", "demo")
        self.mc_version = str(self.config.get("mc_version", "1.21")).strip()
        self.description = self.config.get("description", f"{self.namespace} datapack")
        self.overwrite = self.config.get("overwrite", True)

        # 环境适配
        self.pack_format = self._infer_pack_format()

        # 编译器组件
        self.analyzer = SemanticAnalyzer()
        self.files: Dict[str, Any] = {}

    def _infer_pack_format(self) -> int:
        v = self.mc_version
        if v in self.VERSION_TO_PACK_FORMAT:
            return self.VERSION_TO_PACK_FORMAT[v]
        # 尝试前缀匹配
        for ver, fmt in sorted(self.VERSION_TO_PACK_FORMAT.items(), reverse=True):
            if v.startswith(ver):
                return fmt
        return 48

    def _normalize_path(self, path: str) -> str:
        """规范化路径：统一分隔符，1.21+ 自动转单数形式"""
        path = str(path).strip().replace("\\", "/")

        # 如果是 pack.mcmeta，直接返回
        if path == "pack.mcmeta":
            return path

        # 1.20.4 及以下 (pack_format < 48)，保持复数形式，只处理命名空间
        if self.pack_format < 48:
            # 确保 tags 使用 minecraft 命名空间（如果是函数标签）
            if "tags/functions" in path and not path.startswith("data/minecraft/"):
                path = re.sub(r'^data/[^/]+/tags/', 'data/minecraft/tags/', path)
            return path

        # 1.21+ (pack_format >= 48)：转换为单数形式
        # 1. 先处理文件夹级别的复数（如 functions/, loot_tables/）
        for plural, singular in self.SINGULAR_MAPPINGS.items():
            # 匹配 /functions/ -> /function/
            pattern = f'/{plural}/'
            replacement = f'/{singular}/'
            path = path.replace(pattern, replacement)

        # 2. 确保 tags 使用 minecraft 命名空间，且内部也是单数
        if "/tags/" in path:
            # 强制替换为 minecraft 命名空间
            path = re.sub(r'^data/[^/]+/tags/', 'data/minecraft/tags/', path)

            # 确保 tags/ 后面是单数 (tags/functions -> tags/function)
            for plural, singular in self.SINGULAR_MAPPINGS.items():
                # 匹配 tags/functions/ -> tags/function/
                old_tag = f'/tags/{plural}/'
                new_tag = f'/tags/{singular}/'
                path = path.replace(old_tag, new_tag)

        return path

    def _extract_tag_values(self, content) -> set:
        """从 Tag 内容中提取 values 集合"""
        if isinstance(content, dict):
            values = content.get('values', [])
            if isinstance(values, list):
                return set(values)
        elif isinstance(content, list):
            # 如果直接是列表，视为 values
            return set(content)
        return set()

    def compile_source(self, source: Union[str, Path]) -> 'DatapackWriter':
        """编译源代码并添加到文件列表"""
        if not CodeGenerator:
            raise RuntimeError("无法编译：缺少 CodeGenerator 模块。")

        # 读取代码
        if isinstance(source, (str, Path)) and os.path.exists(source):
            with open(source, 'r', encoding='utf-8') as f:
                code = f.read()
        else:
            code = str(source)

        print(f"[Compiler] 正在编译命名空间: {self.namespace} (MC {self.mc_version}, format {self.pack_format})...")

        try:
            # 语法分析
            ast = parse(code)

            # 语义分析
            self.analyzer.analyze(ast)

            # 代码生成
            gen = CodeGenerator(namespace=self.namespace)
            generated_files = gen.generate(ast)

            # 添加到文件列表（稍后统一规范化）
            for path, content in generated_files.items():
                # 修复 JSON 内容格式
                if path.endswith('.json') and isinstance(content, list):
                    if content and isinstance(content[0], str):
                        try:
                            parsed = json.loads(content[0])
                            content = parsed
                        except json.JSONDecodeError:
                            content = "\n".join(content)
                    elif not content:
                        content = {}

                self.files[path] = content

            print(f"[Compiler] 编译成功！生成 {len(generated_files)} 个文件")

        except Exception as e:
            print(f"[Compiler] 编译失败: {e}")
            raise

        return self

    def add_file(self, path: str, content: Union[dict, list, str]) -> 'DatapackWriter':
        """手动添加文件"""
        self.files[path] = content
        return self

    def write(self):
        """物理写入磁盘 - 智能合并与版本适配"""
        if self.output_path.exists():
            if self.overwrite:
                shutil.rmtree(self.output_path)
            else:
                print(f"[Datapack] 路径已存在且不允许覆盖: {self.output_path}")
                return

        # 确保 pack.mcmeta 存在
        if "pack.mcmeta" not in self.files:
            self.files["pack.mcmeta"] = {
                "pack": {
                    "pack_format": self.pack_format,
                    "description": self.description
                }
            }

        normalized_files: Dict[str, Any] = {}
        tag_registry: Dict[str, set] = {}  # 用于合并同名 tag：{path: set(values)}

        for raw_path, content in self.files.items():
            # 1. 版本规范化（复数->单数，强制 minecraft 命名空间等）
            norm_path = self._normalize_path(raw_path)

            # 2. 检测是否是 Tag 文件（路径中含 /tags/ 且是 .json）
            if '/tags/' in norm_path and norm_path.endswith('.json'):
                values = self._extract_tag_values(content)

                # 注册到 tag_registry 进行合并
                if norm_path not in tag_registry:
                    tag_registry[norm_path] = set()
                tag_registry[norm_path].update(values)
            else:
                # 非 Tag 文件，直接存入（如果有重复，后者覆盖前者）
                normalized_files[norm_path] = content

        # 3. 将合并后的 Tags 写入 normalized_files
        if tag_registry:
            print(f"[Datapack] 合并标签文件:")
            for tag_path, values in sorted(tag_registry.items()):
                normalized_files[tag_path] = {"values": sorted(list(values))}  # 排序保证输出稳定
                print(f"  ✓ {tag_path}: {len(values)} 个条目")

        # ========== 写入磁盘 ==========
        written_count = 0
        for path, content in normalized_files.items():
            full_path = self.output_path / path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, 'w', encoding='utf-8') as f:
                if path.endswith('.json') or path == "pack.mcmeta":
                    if isinstance(content, (dict, list)):
                        json.dump(content, f, indent=4, ensure_ascii=False)
                    else:
                        f.write(str(content))
                elif isinstance(content, list):
                    f.write("\n".join(str(line) for line in content))
                else:
                    f.write(str(content))

            written_count += 1

        print(f"[Datapack] 成功生成至: {self.output_path}")
        print(f"[Datapack] 版本: {self.mc_version} (pack_format: {self.pack_format})")
        print(f"[Datapack] 写入文件数: {written_count}")

        # 最终验证：确保没有复数路径残留（1.21+）
        if self.pack_format >= 48:
            self._validate_singular_paths()

    def _validate_singular_paths(self):
        """验证：1.21+ 环境下不应存在复数路径"""
        plural_patterns = ['functions/', 'loot_tables/', 'recipes/', 'advancements/',
                           'structures/', 'predicates/']
        issues = []

        for path in self.output_path.rglob("*"):
            if path.is_file():
                str_path = str(path).replace("\\", "/")
                for plural in plural_patterns:
                    if f"/{plural}" in str_path:
                        issues.append(str_path)
                        break

        if issues:
            print(f"[Datapack] ⚠ 警告: 发现以下复数路径文件（可能影响 1.21+ 兼容性）:")
            for issue in issues[:5]:
                print(f"    - {issue}")
            if len(issues) > 5:
                print(f"    ... 还有 {len(issues) - 5} 个")