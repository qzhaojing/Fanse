import os
import sys
import glob
import time
import logging
# import multiprocessing
import argparse
import gzip
import shutil
import tempfile
# from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple
from collections import OrderedDict

# pip install colorama
try:
    from colorama import init, Fore, Style
    init()  # Windows下启用颜色支持，没装也没关系，黑白显示就好了
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False
    if not HAS_COLORAMA:
        print("提示: 安装 colorama 可获得更好的彩色输出体验 (pip install colorama)")
# 在命令行添加 --debug 参数即可启用验证模式：
# class PathStatus(Enum):
#     VALID = 0
#     NOT_EXIST = 1   # 致命错误
#     INVALID_TYPE = 2 # 致命错误
#     LONG_PATH = 3   # 警告
#     UNWRITABLE = 4  # 警告

# 配置系统 - 自定义键值对  格式

# %   %  


class ConfigManager:
    """配置管理器，使用自定义键值对格式存储配置"""

    def __init__(self):
        self.config_dir = self._get_config_dir()
        self.config_file = self.config_dir / "fanse3.cfg"

        # 确保配置目录存在
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _get_config_dir(self) -> Path:
        """获取配置目录位置（兼容Windows和Linux）"""
        if os.name == 'nt':  # Windows
            # 使用LOCALAPPDATA或APPDATA
            appdata = os.environ.get('LOCALAPPDATA') or os.environ.get(
                'APPDATA') or os.path.expanduser("~")
            return Path(appdata) / 'Fansetools'
        else:  # Linux/macOS
            return Path.home() / '.config' / 'fansetools'

    def load_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """从配置文件加载配置项"""
        if not self.config_file.exists():
            return default

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception:
            return default

        config_dict = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip()
                config_dict[k] = v

        return config_dict.get(key, default)

    def save_config(self, key: str, value: str):
        """保存配置项到配置文件"""
        # 读取现有配置
        config_lines = []
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception:
                lines = []

            # 处理注释和空行
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    config_lines.append(line.rstrip())  # 保留原样
                else:
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip()
                        config_lines.append(f"{k} = {v}")

        # 更新或添加新的配置项
        updated = False
        new_config_lines = []
        for line in config_lines:
            if '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                if k == key:
                    new_config_lines.append(f"{key} = {value}")
                    updated = True
                else:
                    new_config_lines.append(line)
            else:
                new_config_lines.append(line)

        if not updated:
            new_config_lines.append(f"{key} = {value}")

        # 写入文件
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(new_config_lines) + "\n")
        except Exception as e:
            print(f"保存配置失败: {str(e)}", file=sys.stderr)


class FanseRunner:
    """FANSe3 批量运行器 - 支持多种输入输出模式和交互菜单"""

    FANSE_EXECUTABLES = [
        "FANSe3g.exe", "FANSe3.exe", "FANSe3g", "FANSe3", "Fanse",
        "fanse3g.exe", "fanse3.exe", "fanse3g", "fanse3", "fanse",
    ]

    def __init__(self, debug=False, log_path: Optional[Path] = None):
        # 如果没有colorama，提示

        # 默认参数配置
        # self.default_params = {
        #     'L': 1000,      # 最大读长
        #     'E': '5',       # 错误数量
        #     'S': 13,        # Seed长度
        #     'H': 1,         # 每批次读取reads数(百万)
        #     'C': max(1, multiprocessing.cpu_count() / 2)  # 默认核数(总核数/2)
        # }
        # self.default_options = ['--indel', '--rename']

        self.default_params = {
            # 'L': 1000,      # 最大读长
            # 'E': '5',       # 错误数量
            # 'S': 13,        # Seed长度
            # 'H': 1,         # 每批次读取reads数(百万)
            # 'C': int(max(1, multiprocessing.cpu_count() / 2)),  # 默认核数(总核数/2)
        }
        self.default_options = []

        # 配置管理
        self.config = ConfigManager()

        # 日志初始化
        # self._init_logger()
        self._init_logger(log_path)
        self.debug = debug  # 存储为实例属性

        # 处理工作目录
        self.temp_files: List[Path] = []  # 添加临时文件跟踪
        self.work_dir: Optional[Path] = None  # 添加work_dir属性
# =============================================================================
# 配置工作目录tmp_dir
# =============================================================================

    def set_work_dir(self, work_dir: Optional[str]):
        """设置工作目录"""
        if not work_dir:
            self.work_dir = None
            return

        try:
            self.work_dir = self._prepare_work_dir(work_dir)
        except Exception as e:
            self.logger.error(f"设置工作目录失败: {str(e)}")
            self.work_dir = None

    def _prepare_work_dir(self, work_dir: Optional[str]) -> Optional[Path]:
        """准备并验证工作目录"""
        if not work_dir:
            return None

        # 转换为Path对象并创建目录
        work_path = Path(work_dir).resolve()

        # 验证路径
        if not work_path.exists():
            work_path.mkdir(parents=True, exist_ok=True)
        elif not work_path.is_dir():
            raise ValueError(f"指定路径不是目录: {work_path}")

        # 检查可写权限
        test_file = work_path / "write_test.tmp"
        try:
            test_file.touch()
            test_file.unlink()
        except OSError as e:
            raise PermissionError(f"无法写入指定目录 {work_path}: {str(e)}")

        self.logger.info(f"使用工作目录: {work_path}")
        return work_path

    def _cleanup(self):
        """清理所有临时文件"""
        for file in self.temp_files:
            try:
                if file.exists():
                    file.unlink()
                    self.logger.debug(f"已清理临时文件: {file}")
            except Exception as e:
                self.logger.warning(f"清理临时文件失败 {file}: {str(e)}")
        self.temp_files = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._cleanup()

# =============================================================================
# 配置日志
# =============================================================================
    def _init_logger(self, custom_log_path: Optional[Path] = None):
        """初始化日志系统"""
        self.logger = logging.getLogger('fanse.run')
        self.logger.setLevel(logging.INFO)

        # # 创建日志格式
        # formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        # 创建日志格式 - 时间到秒（无毫秒）
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'  # 新增datefmt参数指定到秒
        )

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # 确定日志文件路径
        if custom_log_path:
            # 使用自定义路径
            log_file = custom_log_path
        else:
            # 默认路径：配置目录下的 fanse_run.log
            log_file = self.config.config_dir / 'fanse_run.log'

        # 文件处理器
        try:
            # 确保日志目录存在
            log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
            self.logger.info(f"日志文件: {log_file}")
        except Exception as e:
            self.logger.error(f"无法创建日志文件: {str(e)}")

        # # 文件处理器
        # log_file = self.config.config_dir / 'fanse_run.log'
        # try:
        #     file_handler = logging.FileHandler(log_file, encoding='utf-8')
        #     file_handler.setFormatter(formatter)
        #     self.logger.addHandler(file_handler)
        # except Exception as e:
        #     self.logger.error(f"无法创建日志文件: {str(e)}")

    # def _format_path_for_system(self, path: Path) -> str:
    #     """根据操作系统类型返回适配的路径字符串"""
    #     path_str = str(path.resolve())
    #     if os.name == 'nt':  # Windows系统
    #         # 转换为Windows原生反斜杠，并确保引号包裹
    #         return f'"{path_str.replace("/", "\\")}"'
    #     else:  # Linux/macOS
    #         # 保持正斜杠，并确保引号包裹
    #         return f'"{path_str}"'

    def _normalize_path(self, path: Union[str, Path]) -> Path:
        """规范化路径处理，完全支持UNC和所有Windows路径"""
        path = Path(path)

        # 处理网络路径（UNC）的特殊情况
        path_str = str(path)
        if path_str.startswith(('\\\\', '//')):
            # 手动构建UNC路径
            unc_path = path_str.replace('/', '\\')
            return Path(unc_path)

        try:
            # 优先尝试解析路径
            return path.resolve()
        except:
            try:
                # 回退到绝对路径
                return path.absolute()
            except:
                # 最后尝试处理原始路径
                return path

# =============================================================================
# set the FANSe3 folder position
# =============================================================================
    def find_fanse_executable(self, directory: Path) -> Optional[Path]:
        """在目录中查找FANSe可执行文件"""
        for root, _, files in os.walk(directory):
            for file in files:
                if file in self.FANSE_EXECUTABLES:
                    return Path(root) / file
        return None

    def get_fanse3_path(self) -> Optional[Path]:
        """获取完整的FANSe可执行文件路径（修正目录处理）"""
        path_str = self.config.load_config('fanse3dir')
        if not path_str:
            return None

        path = self._normalize_path(path_str)

        # 如果是文件，直接返回
        if path.is_file():
            return path

        # 如果是目录，查找目录中的可执行文件
        if path.is_dir():
            executable = self.find_fanse_executable(path)
            if executable:
                return executable
            else:
                self.logger.warning(f"在目录中未找到FANSe可执行文件: {path}")
                return None

        # 路径不存在
        self.logger.warning(f"配置的FANSe路径不存在: {path}")
        return None

    def set_fanse3_path(self, path: Union[str, Path]):
        """设置FANSe3路径（自动查找可执行文件）"""
        path = self._normalize_path(path)
        if not path.exists():
            raise FileNotFoundError(f"路径不存在: {path}")

        # 如果是目录，查找可执行文件
        if path.is_dir():
            executable = self.find_fanse_executable(path)
            if not executable:
                raise FileNotFoundError(f"目录中未找到FANSe可执行文件: {path}")
            path = executable

        # 保存配置
        self.config.save_config('fanse3dir', str(path))
        self.logger.info(f"FANSe路径配置成功: {path}")
# =============================================================================
# Generate the input and output file and folder
# =============================================================================

    def parse_input(self, input_str: str) -> List[Path]:
        """解析输入路径字符串，支持多种格式（修正目录处理）"""
        input_items = [item.strip()
                       for item in input_str.split(',') if item.strip()]
        input_paths = []

        for item in input_items:
            # 移除可能包裹在路径两端的引号（单引号或双引号），引号容易引发问题，干脆都去掉，还有末尾的'/'
            item = item.strip('\'"')
            try:
                # 处理通配符
                if '*' in item or '?' in item:
                    matched_paths = glob.glob(item)  # 查找  path/*.fq
                    if not matched_paths:
                        self.logger.warning(f"未找到匹配的文件: {item}")
                        continue
                    for mp in matched_paths:
                        p = self._normalize_path(mp)
                        if p.exists():
                            if p.is_file():
                                input_paths.append(p)
                            elif p.is_dir():
                                # 目录：添加目录下所有fastq文件
                                self._add_fastq_files(p, input_paths)
                        else:
                            self.logger.warning(f"这路径需要再检查一下: {mp}")
                else:  # 没有通配符，只是单纯文件或者文件夹列表
                    p = self._normalize_path(item)
                    if p.exists():
                        if p.is_file():  # 如果是文件
                            input_paths.append(p)
                        elif p.is_dir():  # 如果是目录
                            # 目录：添加目录下所有fastq,fq,gz.fq.fastq.gz等等文件
                            self._add_fastq_files(p, input_paths)
                    else:
                        self.logger.warning(f"这路径需要再检查一下: {item}")
            except Exception as e:
                self.logger.error(f"解析输入input的路径失败了: {item} - {str(e)}")

        return input_paths

    def _add_fastq_files(self, directory: Path, file_list: list):
        """将目录下的fastq文件添加到文件列表"""
        # 支持的fastq文件扩展名
        fastq_exts = ['.fastq', '.fq', '.fastq.gz', '.fq.gz']
        for ext in fastq_exts:
            for file in directory.glob(f'*{ext}'):
                if file.is_file():
                    file_list.append(file)
            # 考虑可能有大写扩展名
            for file in directory.glob(f'*{ext.upper()}'):
                if file.is_file() and file not in file_list:
                    file_list.append(file)

    # def _handle_gzipped_input(self, input_file: Path, temp_dir: Optional[Path] = None) -> Tuple[Path, Optional[Path]]:
    def _handle_gzipped_input(self, input_file: Path) -> Tuple[Path, Optional[Path]]:
        """处理gzipped输入文件，返回实际输入文件路径和临时文件（如果有）

        Args:
            input_file: 输入文件路径
            temp_dir: 可选的自定义临时文件夹目录（防止系统盘空间满）

        Returns:
            (实际输入文件路径, 临时文件路径)
        """

        # 1. 检查是否需要解压
        if input_file.suffix != '.gz' and not (len(input_file.suffixes) > 1 and input_file.suffixes[-1] == '.gz'):
            return input_file, None

        try:
            # 在 _handle_gzipped_input 中添加
            # 2. 创建自定义临时目录（如果需要）
            custom_temp_dir = self.work_dir if self.work_dir else None
            if custom_temp_dir:
                custom_temp_dir.mkdir(parents=True, exist_ok=True)
                input_size = input_file.stat().st_size
                disk_free = shutil.disk_usage(custom_temp_dir).free
                if disk_free < input_size * 6:  # 预留6倍空间
                    raise RuntimeError("磁盘空间不足,请用-w,--work_dir 设置到其他位置")

            # 3. 创建临时文件（带自定义目录支持）
            with tempfile.NamedTemporaryFile(
                prefix=f"{input_file.stem}_",
                suffix=".fastq",
                dir=custom_temp_dir,  # 添加自定义目录参数
                delete=False
            ) as temp_file:
                temp_path = Path(temp_file.name)

                # 4. 解压文件
                self.logger.info(f"解压文件: {input_file} -> {temp_path}")
                with gzip.open(input_file, 'rb') as f_in, \
                        open(temp_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

                # 添加到临时文件列表
                self.temp_files.append(temp_path)
                return temp_path, temp_path

        except Exception as e:
            self.logger.error(f"解压文件失败: {input_file} - {str(e)}")
            raise

    # def _handle_gzipped_input(self, input_file: Path) -> Tuple[Path, Optional[Path]]:
    #     """处理gzipped输入文件，返回实际输入文件路径和临时文件（如果有）"""
    #     # 检查是否是需要解压的gzip文件
    #     if input_file.suffix != '.gz' and not (len(input_file.suffixes) > 1 and input_file.suffixes[-1] == '.gz'):
    #         return input_file, None

    #     try:
    #         # 创建临时文件（不自动删除）
    #         temp_file = Path(tempfile.NamedTemporaryFile(
    #             prefix=f"{input_file.stem}_",
    #             suffix=".fastq",
    #             delete=False
    #         ).name)

    #         # 解压gz文件到临时文件
    #         self.logger.info(f"解压文件: {input_file} -> {temp_file}")
    #         with gzip.open(input_file, 'rb') as f_in:
    #             with open(temp_file, 'wb') as f_out:
    #                 shutil.copyfileobj(f_in, f_out)

    #         return temp_file, temp_file

    #     except Exception as e:
    #         self.logger.error(f"解压文件失败: {input_file} - {str(e)}")
    #         raise

    def generate_output_mapping(self, input_paths: List[Path],
                                output_paths: Optional[List[Path]] = None) -> Dict[Path, Path]:
        """        
        生成输入输出路径映射（支持文件和文件夹输入）

        参数:
            input_paths: 输入路径列表（可以是文件或文件夹）
            output_paths: 可选输出路径列表

        返回:
            输入路径到输出路径的映射字典

        """

        path_map = OrderedDict()

        # 展开所有输入路径（处理文件夹情况）
        expanded_inputs = []
        for path in input_paths:
            if path.is_file():
                expanded_inputs.append(path)
            elif path.is_dir():
                # 收集文件夹下所有文件（不递归）
                expanded_inputs.extend(
                    [f for f in path.iterdir() if f.is_file()])
            else:
                raise ValueError(f"路径既不是文件也不是文件夹: {path}")

        # 辅助函数：智能生成输出文件名
        def get_output_filename(input_file: Path) -> str:
            """根据输入文件名生成输出文件名，处理压缩文件扩展名"""
            stem = input_file.stem

            # 处理常见的压缩文件扩展名
            compress_exts = ['.gz', '.bz2', '.zip']
            for ext in compress_exts:
                if stem.endswith(ext):
                    stem = stem[:-len(ext)]

            # 处理常见的测序文件扩展名
            seq_exts = ['.fastq', '.fq', '.fa', '.fna', '.fasta']
            for ext in seq_exts:
                if stem.endswith(ext):
                    stem = stem[:-len(ext)]

            return f"{stem}.fanse3"

        if output_paths is None:
            for path in expanded_inputs:
                # 使用智能文件名生成
                output_file = path.with_name(get_output_filename(path))
                path_map[path] = output_file

        # 2. 指定单个输出路径
        elif len(output_paths) == 1:
            output_dir = self._normalize_path(output_paths[0])
            output_dir.mkdir(parents=True, exist_ok=True)
            for path in expanded_inputs:
                # 使用智能文件名生成
                output_file = output_dir / get_output_filename(path)
                path_map[path] = output_file

        # 3. 多个输出路径（必须与输入数量匹配）
        else:
            if len(expanded_inputs) != len(output_paths):
                raise ValueError(
                    f"输入路径({len(expanded_inputs)})和输出路径({len(output_paths)})数量不匹配")

            for input_path, output_dir in zip(expanded_inputs, output_paths):
                output_dir = self._normalize_path(output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                # 使用智能文件名生成
                output_file = output_dir / get_output_filename(input_path)
                path_map[input_path] = output_file

        return path_map
    # def generate_output_mapping(self, input_paths: List[Path],
    #                          output_paths: Optional[List[Path]] = None) -> Dict[Path, Path]:
    #     """
    #     生成输入输出路径映射（支持文件和文件夹输入）

    #     参数:
    #         input_paths: 输入路径列表（可以是文件或文件夹）
    #         output_paths: 可选输出路径列表

    #     返回:
    #         输入路径到输出路径的映射字典

    #     """

    #     path_map = OrderedDict()

    #     # 展开所有输入路径（处理文件夹情况）
    #     expanded_inputs = []
    #     for path in input_paths:
    #         if path.is_file():
    #             expanded_inputs.append(path)
    #         elif path.is_dir():
    #             # 收集文件夹下所有文件（不递归）
    #             expanded_inputs.extend([f for f in path.iterdir() if f.is_file()])
    #         else:
    #             raise ValueError(f"路径既不是文件也不是文件夹: {path}")

    #     if output_paths is None:
    #         for path in expanded_inputs:
    #             output_file = path.with_name(f"{path.stem}.fanse3")
    #             path_map[path] = output_file

    #     # 2. 指定单个输出路径
    #     elif len(output_paths) == 1:
    #         output_dir = self._normalize_path(output_paths[0])
    #         output_dir.mkdir(parents=True, exist_ok=True)
    #         for path in expanded_inputs:
    #             output_file = output_dir / f"{path.stem}.fanse3"
    #             path_map[path] = output_file

    #     # 3. 多个输出路径（必须与输入数量匹配）
    #     else:
    #         if len(expanded_inputs) != len(output_paths):
    #             raise ValueError(f"输入路径({len(expanded_inputs)})和输出路径({len(output_paths)})数量不匹配")

    #         for input_path, output_dir in zip(expanded_inputs, output_paths):
    #             output_dir = self._normalize_path(output_dir)
    #             output_dir.mkdir(parents=True, exist_ok=True)
    #             output_file = output_dir / f"{input_path.stem}.fanse3"
    #             path_map[input_path] = output_file

    #     return path_map


# =============================================================================
# Start to integrate the paras  to single cmd
# =============================================================================

    def build_command(self, input_file: Path, output_file: Path,
                      refseq: Path, params: Dict[str, Union[int, str]],
                      options: List[str]) -> str:
        """构建FANSe3命令 - 优化引号使用"""
        fanse_path = self.get_fanse3_path()
        if not fanse_path:
            raise RuntimeError("未配置FANSe路径")

        # 验证路径存在
        if not input_file.exists():
            raise FileNotFoundError(f"输入文件没找到: {input_file}")
        if not refseq.exists():
            raise FileNotFoundError(f"参考序列文件没找到: {refseq}")

        # 确保输出文件的父目录存在
        if not output_file.parent.exists():
            print(f"结果输出文件夹不存在，将新建: {refseq}")
            output_file.parent.mkdir(parents=True, exist_ok=True)

        cmd_fanseparts = [
            str(fanse_path),  # 直接使用字符串路径
            f'-R{str(refseq)}',    # 参数值直接拼接
            f'-D{str(input_file)}',
            f'-O{str(output_file)}'
        ]

        # 添加参数（确保格式一致）
        for param, value in params.items():
            # fanse参数和值之间千万不要添加空格，排查要死人的
            cmd_fanseparts.append(f"-{param}{value}")

        # 添加选项
        cmd_fanseparts.extend(options)

        # 记录最终命令用于调试
        final_cmd = " ".join(cmd_fanseparts)
        self.logger.debug(f"最终命令: {final_cmd}")
        return final_cmd

    def _print_task_info(self, task_info: str):
        """专用方法处理控制台的任务信息打印"""
        # 同时打印彩色（示例，假设我们有彩色支持）
        try:
            print(Fore.CYAN + task_info + Style.RESET_ALL)
        except ImportError:
            print(task_info)

    def log_path_diagnostics(self, path_name, path):
        """记录路径诊断信息"""
        self.logger.debug(
            f"生成命令路径格式 - 系统类型: {'Windows' if os.name == 'nt' else 'Linux'}")
        # self.logger.debug(f"可执行文件路径: {self._format_path_for_system(fanse_path)}")
        self.logger.debug(f"{path_name}: {path}")
        self.logger.debug(f"  绝对路径: {path.absolute()}")
        self.logger.debug(f"  真实路径: {path.resolve()}")
        self.logger.debug(f"  是否存在: {path.exists()}")

        if path.exists():
            self.logger.debug(f"  是文件: {path.is_file()}")
            self.logger.debug(f"  是目录: {path.is_dir()}")
        self.logger.debug(f"  父目录: {path.parent}")
        self.logger.debug(f"  父目录是否存在: {path.parent.exists()}")

    def validate_paths(self, path: Path, name: str,
                       is_file: bool = False, is_dir: bool = False
                       ) -> Tuple[bool, List[str]]:
        """集中验证路径，返回验证状态与错误信息"""
        errors = []

        # 1. 存在性检查
        if not path.exists():
            errors.append(f"{name}不存在: {path}")
            return False, errors

        # 2. 类型检查
        if is_file and not path.is_file():
            errors.append(f"{name}不是文件: {path}")
        if is_dir and not path.is_dir():
            errors.append(f"{name}不是目录: {path}")

        # 3. 路径长度检查（Windows限制）
        path_str = str(path.resolve())
        if len(path_str) > 150:  # 预警阈值
            errors.append(f"{name}路径过长（{len(path_str)}字符）: {path}")

        # 4. 可访问性检查（针对输出目录）
        if is_dir:
            test_file = path / "fanse_debug_test.tmp"
            try:
                test_file.touch()
                test_file.unlink()
            except PermissionError:
                errors.append(f"{name}目录不可写: {path}")

        return len(errors) == 0, errors

    def run_batch(self, file_map: Dict[Path, Path], refseq: Path,
                  params: Optional[Dict[str, Union[int, str]]] = None,
                  options: Optional[List[str]] = None,
                  debug: bool = False,
                  ):
        """批量运行FANSe3（添加执行确认选项）"""
        # 合并参数和选项
        final_params = {**self.default_params, **(params or {})}
        final_options = [*self.default_options, *(options or [])]

        # 验证参考序列存在
        if not refseq.exists():
            raise FileNotFoundError(f"参考序列文件不存在: {refseq}")

        # 显示配置信息
        self.logger.info("\n" + "="*50)
        self.logger.info("FANSe3 运行配置:")
        self.logger.info(f"  参考序列: {refseq}")
        self.logger.info(f"  输入文件: {len(file_map)} 个")
        self.logger.info(f"  参数: {final_params}")
        self.logger.info(f"  选项: {final_options}")
        self.logger.info("="*50)

        # 统计处理进度
        total = len(file_map)
        success = 0
        failed = []

        # 执行模式控制
        run_mode = "confirm"  # 默认：每个命令前需要确认
        print("\n执行模式：")
        print(" - 默认模式下'y'会一次性运行所有检测到的fq任务")
        print(" - 输入 'a' 可切换为单条执行所有剩余任务\n")
        # 新增调试模式检查
        # debug = getattr(self, 'debug', False)  # 检查是否启用--debug

        # 开始处理
        start_time = time.time()
        with self:
            for i, (original_input_file, output_file) in enumerate(file_map.items(), 1):
                # 构建命令

                temp_file = None

                try:
                    # 处理可能的gzipped输入
                    input_file, temp_file = self._handle_gzipped_input(
                        original_input_file)
                except:
                    # 如果检测不是gzfile，则还是input_file   (*.fastq)
                    input_file = original_input_file

                cmd = self.build_command(
                    input_file, output_file, refseq, final_params, final_options)

                # 准备任务信息
                task_info = f"""
                            {'='*48}
                            任务 {i}/{total}: {input_file.name}
                            {'='*48}
                            原始输入文件: {original_input_file}
                            {'临时文件: ' + str(temp_file) if temp_file else 'None'}
                            # 实际输入文件: {input_file}
                            输出文件: {output_file}
                            参考序列: {refseq}
                            参数: {final_params}
                            选项: {final_options}
                            命令: {cmd}
                            {'-'*48}
                            """

                # 显示任务信息（调试模式下简化输出）
                if not debug:
                    # self.logger.info(task_info)
                    self._print_task_info(task_info)  # 专门处理控制台打印
                    # self.logger.info(task_info)       # 同时记录到日志
                    if temp_file:
                        self.logger.info(f"临时文件将在完成后删除: {temp_file}")
                else:
                    print(task_info)  # 正常模式直接打印到控制台

                # =============== 新增路径验证逻辑 ===============
                if debug:
                    self.logger.info("调试模式激活 - 开始路径验证")
                    all_errors = []

                    # 统一调用验证方法
                    for path, name, check_type in [
                        (input_file, "输入文件", {"is_file": True}),
                        (refseq, "参考序列", {"is_file": True}),
                        # (output_file, "输出文件", {"is_file": True})
                    ]:
                        is_valid, errors = self.validate_paths(
                            path, name, **check_type)
                        all_errors.extend(errors)

                    # 输出验证报告
                    if not all_errors:
                        self.logger.info("✅ 所有路径验证通过")
                    else:
                        self.logger.error("🚫 路径验证失败：")
                        for error in all_errors:
                            self.logger.error(f"   - {error}")
                    return

                # =============== 调试逻辑结束 ===============

                # 执行确认（在DEBUG模式下跳过）
                if run_mode == "confirm" and not self.logger.isEnabledFor(logging.DEBUG):

                    # 修改后的交互选项
                    response = input(
                        "是否执行此任务? [y]全部执行, [a]执行单条, [n]跳过单条, [q]退出: ").strip().lower()

                    if response == 'q':
                        self.logger.info("用户选择退出程序")
                        break
                    elif response == 'n':
                        self.logger.info("用户选择跳过此任务")
                        continue
                    elif response == 'a':
                        self.logger.info("用户选择执行此单条任务")
                    elif response == 'y':
                        run_mode = "auto"
                        self.logger.info("用户选择全部执行所有任务")

                # # # 执行前路径诊断
                # self.log_path_diagnostics("输入文件", input_file)
                # self.log_path_diagnostics("输出目录", output_file)
                # self.log_path_diagnostics("参考序列", refseq)

                try:
                    # 执行命令
                    self.logger.info("开始执行命令...")
                    cmd_start_time = time.time()
                    ret = os.system(cmd)
                    elapsed = time.time() - cmd_start_time

                    if ret == 0:
                        success += 1
                        self.logger.info(f"  完成了! 耗时: {elapsed:.2f}秒")

                        # 检查预期的输出文件
                        expected_output = output_file
                        if expected_output.exists():
                            self.logger.info(f"  找到输出文件: {expected_output}")
                        else:
                            self.logger.warning(
                                f"  警告: 未找到预期输出文件 {expected_output}")
                    else:
                        failed.append(input_file.name)
                        self.logger.error(
                            f"  失败! 返回码: {ret}, 耗时: {elapsed:.2f}秒")

                except Exception as e:
                    failed.append(original_input_file.name)
                    self.logger.error(f"  处理异常: {str(e)}")
                finally:
                    # 清理临时文件（如果创建了）
                    if temp_file and temp_file.exists():
                        try:
                            temp_file.unlink()
                            self.logger.info(f"已清理临时文件: {temp_file}")
                        except Exception as e:
                            self.logger.error(
                                f"清理临时文件失败: {temp_file} - {str(e)}")

        # 汇总统计（美化显示）
        total_elapsed = time.time() - start_time
        summary = f"\n{'='*50}\n处理完成: {success} 成功, {len(failed)} 失败\n总耗时: {total_elapsed:.2f}秒\n"

        self.logger.info(summary)
        if HAS_COLORAMA:
            print(Fore.CYAN + summary + Style.RESET_ALL)
        else:
            print(summary)

        if failed:
            self.logger.info("失败文件列表:")
            if HAS_COLORAMA:
                print(Fore.RED + "失败文件列表:" + Style.RESET_ALL)
            else:
                print("失败文件列表:")
            for name in failed:
                self.logger.info(f"  - {name}")
                if HAS_COLORAMA:
                    print(Fore.RED + f"  - {name}" + Style.RESET_ALL)
                else:
                    print(f"  - {name}")

        # self.logger.info(summary)
        # # print(f"\033[1;36m{summary}\033[0m")  # 青色加粗标题

        # if failed:
        #     self.logger.info("失败文件列表:")
        #     print("\033[31m失败文件列表:\033[0m")  # 红色标题
        #     for name in failed:
        #         self.logger.info(f"  - {name}")
        #         print(f"\033[31m  - {name}\033[0m")

        # # 汇总统计
        # total_elapsed = time.time() - start_time
        # self.logger.info("\n" + "="*50)
        # self.logger.info(f"处理完成: {success} 成功, {len(failed)} 失败")
        # self.logger.info(f"总耗时: {total_elapsed:.2f}秒")
        # if failed:
        #     self.logger.info("失败文件列表:")
        #     for name in failed:
        #         self.logger.info(f"  - {name}")


# =============================================================================
# #未实现，配置参数格式，使之忽略大小写，-i，-I，-e，-E，--indel，--INDEL等通用
# =============================================================================
# class CaseInsensitiveDictAction(argparse.Action):
#     """自定义 action 实现大小写不敏感的参数存储"""
#     def __call__(self, parser, namespace, values, option_string=None):
#         # 获取参数名（转换为小写作为键）
#         key = self.dest.lower()

#         # 创建大小写不敏感的字典（如果还不存在）
#         if not hasattr(namespace, 'case_insensitive_params'):
#             setattr(namespace, 'case_insensitive_params', defaultdict(dict))

#         # 存储参数值（原始大小写形式）
#         namespace.case_insensitive_params[key] = values

# def create_case_insensitive_parser():
#     """创建大小写不敏感的参数解析器"""
#     parser = argparse.ArgumentParser(
#         description='FANSe3 CLI Tool',
#         formatter_class=argparse.RawTextHelpFormatter
#     )

#     # 路径配置
#     parser.add_argument(
#         '--set-path',
#         metavar='PATH',
#         help='配置FANSe可执行文件路径 (文件或目录)'
#     )

#     # 必需参数
#     parser.add_argument(
#         '-i', '--input',
#         dest='INPUT',  # 指定标准化的目标属性名
#         required=False,
#         help='输入文件/目录 (支持通配符，多个用逗号分隔)'
#     )
#     parser.add_argument(
#         '-r', '--refseq',
#         dest='REFSEQ',  # 指定标准化的目标属性名
#         required=False,
#         help='参考序列文件路径'
#     )

#     # 可选参数
#     parser.add_argument(
#         '-o', '--output',
#         dest='OUTPUT',  # 指定标准化的目标属性名
#         help='输出目录'
#     )

#     # 使用自定义 action 实现大小写不敏感的参数
#     for opt in ['O', 'L', 'E', 'S', 'H', 'C', 'T', 'I']:
#         parser.add_argument(
#             f'-{opt}',
#             action=CaseInsensitiveDictAction,
#             dest=f'FANSe_PARAM_{opt}',
#             type=str if opt == 'T' or opt == 'E' else int,
#             metavar='VALUE' if opt != 'T' else 'SPEC',
#             help=f'{opt} 参数的值'  # 实际帮助文本在下面统一设置
#         )

#     # 单独设置帮助文本（避免重复）
#     param_help = {
#         'O': '结果文件夹 (默认: fastq所在文件夹)',
#         'L': '最大读长 (默认: 1000)',
#         'E': '错误数量 (默认: 3)',
#         'S': 'Seed长度 (默认: 13)',
#         'H': '每批次读取reads数(百万) (默认: 1)',
#         'C': '并行核数 (默认: CPU核数-2)',
#         'T': 'START,LENGTH (默认: 0,150)',
#         'I': '不开启0,开启1(默认: 0)'
#     }

#     # 更新参数的帮助文本
#     for action in parser._actions:
#         if action.dest.startswith('FANSe_PARAM_'):
#             opt = action.dest.split('_')[-1]
#             action.help = param_help.get(opt, '')

#     # 其他选项...

#     return parser


# 命令行接口
def add_run_subparser(subparsers):
    """添加run子命令到主解析器"""
    parser = subparsers.add_parser(
        'run',
        help='批量运行FANSe3',
        description='''FANSe3 批量运行工具
支持多种输入输出模式:  单个文件与目录形式均可，可批量运行
  -i sample.fq 文件: 直接处理单个或多个文件。/path/sample.fastq;/path/sample.fq.支持gz读取，会先解压到本地临时目录后输入fanse3比对。可输入多个文件，用逗号隔开

  -i /path/ 目录: 如输入目录，则处理目录下所有fastq/fq/fq.gz/fastq.gz。可同时输入多个目录，用逗号隔开

  -i /*.fq 通配符: 使用通配符选择文件   为高效筛选目录中所需文件，可使用*号进行筛选。例如   /path/*R1.fastq.gz

输出目录控制:
  不指定: 输出到输入文件所在目录
  单目录: 所有输出保存到同一目录  
  多目录: 与输入一一对应的输出目录

  如多目录，最好文本文件记录好命令再运行。
  ''',
        formatter_class=argparse.RawTextHelpFormatter
    )

    # 路径配置
    parser.add_argument(
        '--set-path',
        metavar='PATH',
        help='配置FANSe可执行文件路径 (文件或目录)'
    )

    # 添加work_dir配置 (新增)
    parser.add_argument(
        '-w', '--work_dir',
        type=str,
        default=None,
        help="配置临时工作目录，用于存放解压等操作产生的临时文件"
    )

    # 必需参数（当不设置路径时）
    parser.add_argument(
        '-i', '--input',
        required=False,  # 改为非必需
        help='输入文件/目录 (支持通配符，多个用逗号分隔)'
    )
    parser.add_argument(
        '-r', '--refseq',
        required=False,  # 改为非必需
        help='参考序列文件路径'
    )

    # 可选参数
    parser.add_argument(
        '-o', '--output',
        help='输出目录 (单个或与输入一一对应的多个，用逗号分隔).输出文件或目录（如果是目录会自动添加 input.fanse3）'
    )

    # 新增日志配置参数
    parser.add_argument(
        '--log',
        help='指定日志文件路径（默认保存在配置目录）'
    )
    # 在命令行解析代码中（例如 main.py 或 cli.py）
    parser.add_argument(
        '--debug', action='store_true',
        help='启用调试模式：验证路径是否正确，但不执行比对命令')

    # FANSe3参数
    parser.add_argument(
        '-O', type=int, metavar='output',
        help='结果输出文件夹 (不指定：输入文件夹)'
    )
    parser.add_argument(
        '-L', type=int, metavar='LENGTH',
        help='最大读长 (默认: 1000)'
    )
    parser.add_argument(
        '-E', type=str, metavar='MISMATCH',
        help='错误数量 (默认: 5)'
    )
    parser.add_argument(
        '-S', type=int, metavar='min_LENGTH',
        help='Seed长度 (默认: 13)'
    )
    parser.add_argument(
        '-H', type=int, metavar='MILLIONREADS',
        help='每批次读取reads数(百万) (默认: 1)'
    )
    parser.add_argument(
        '-C', type=int, metavar='CORES',
        help='并行核数 (默认: CPU核数-2)'
    )
    parser.add_argument(
        '-T', type=str, metavar='SPLIT READS',
        help='START,LENGTH (默认: 0,150)'
    )
    parser.add_argument(
        '-I', type=int, metavar='INDEL 0,1',
        help='不开启0,开启1(默认: 0)'
    )
    # FANSe3选项
    parser.add_argument(
        '--all',
        action='store_true',
        help='输出每条read的所有最佳的mapping位点'
    )
    parser.add_argument(
        '--unique',
        action='store_true',
        help='将unique和multi mapped reads分别输出'
    )
    parser.add_argument(
        '--showalign',
        action='store_true',
        help='在结果中输出比对结果'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='以单线程模式运行'
    )
    parser.add_argument(
        '--rename',
        action='store_true',
        help='启用reads改名，改为1，2，3，4……'
    )
    parser.add_argument(
        '--indel',
        action='store_true',
        help='启用indel比对'
    )

    parser.set_defaults(func=run_command)


def run_command(args):
    """处理run子命令"""
    # 处理日志路径
    log_path = Path(args.log) if args.log else None
    if args.log:
        try:
            log_path = Path(args.log)
            # 如果是目录，添加默认文件名
            if log_path.is_dir():
                log_path = log_path / 'fanse_run.log'
        except Exception as e:
            print(f"警告: 指定的日志路径无效 - {str(e)}")

    # 创建运行器实例，传入日志路径
    runner = FanseRunner(log_path=log_path, debug=args.debug)

    try:
        # 处理fanse路径配置
        if args.set_path:
            runner.set_fanse3_path(args.set_path)
            return
        # 设置工作目录
        if args.work_dir:
            runner.set_work_dir(args.work_dir)

        # 如果设置了工作目录，记录日志
        if args.work_dir:
            work_dir = Path(args.work_dir)

            # 确保目录存在
            if not work_dir.exists():
                runner.logger.info(f"创建工作目录: {work_dir}")
                work_dir.mkdir(parents=True, exist_ok=True)
            runner.work_dir = work_dir
            runner.logger.info(f"设置工作目录: {runner.work_dir}")
        runner.logger.info(f"使用设置的工作路径: {runner.work_dir}")
        # 检查FANSe路径
        fanse_path = runner.get_fanse3_path()
        if not fanse_path:
            runner.logger.error("未配置FANSe路径，请先使用 --set-path 配置")
            sys.exit(1)
        runner.logger.info(f"使用FANSe路径: {fanse_path}")

        # 检查是否提供了够运行的最少运行参数
        if not args.input or not args.refseq:
            runner.logger.error("需至少提供 -i/--input 和 -r/--refseq 参数")
            sys.exit(1)

        # 解析输入数据的路径
        input_paths = runner.parse_input(args.input)
        if not input_paths:
            runner.logger.error("未找到有效的输入文件")
            sys.exit(1)

        # 检查是否指定了结果输出目录
        output_paths = None
        if args.output:
            # 支持多种分隔符处理：逗号/分号/空格
            separators = [',', ';', ' ']
            output_list = args.output

            # 尝试找到最适合的分隔符
            for sep in separators:
                if sep in args.output:
                    output_list = [d.strip()
                                   for d in args.output.split(sep) if d.strip()]
                    break
            else:  # 没有分隔符时视为单个路径
                output_list = [args.output.strip()]

            output_paths = [Path(d) for d in output_list]

        # 关键点：生成路径映射必须保留
        path_map = runner.generate_output_mapping(input_paths, output_paths)

        # 准备参数
        params = {
            key: value for key, value in [
                ('O', args.O),
                ('L', args.L),
                ('E', args.E),
                ('S', args.S),
                ('H', args.H),
                ('C', args.C),
                ('T', args.T),
                # ('I', args.I),
            ] if value is not None
        }

        # 准备选项
        options = [
            opt for opt, flag in [
                ('--all', args.all),
                ('--unique', args.unique),
                ('--showalign', args.showalign),
                ('--test', args.test),
                ('--indel', args.indel),
            ] if flag
        ]

        # 运行批处理
        runner.run_batch(
            file_map=path_map,
            refseq=Path(args.refseq),
            params=params,
            options=options,
            debug=args.debug  # 添加debug参数
        )

    except Exception as e:
        runner.logger.error(f"运行失败，命令行末尾加上--debug试一下: {str(e)}")
        sys.exit(1)
    finally:
        # 结束后确保清理临时文件
        runner._cleanup()


# 如果独立运行，则测试
if __name__ == "__main__":
    # 测试配置
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_run_subparser(subparsers)

    # 模拟参数
    args = parser.parse_args(['run', '--set-path', '.'])
    args.func(args)
