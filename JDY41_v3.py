#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JDY-41 Configuration Tool
A modern GUI tool for configuring JDY-41 wireless modules via serial port.
"""

import sys
import os
import json
import random
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGroupBox, QLabel, QComboBox,
                             QPushButton, QTextEdit, QLineEdit, QCheckBox,
                             QRadioButton, QButtonGroup, QStatusBar, QMessageBox,
                             QGridLayout, QSplitter, QFrame, QDialog, QDialogButtonBox,
                             QSpinBox, QMenuBar, QAction, QMenu, QInputDialog,
                             QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QEventLoop, QUrl
from PyQt5.QtGui import QFont, QColor, QTextCursor, QPixmap, QDesktopServices


# ========================== Serial Reader Thread ==========================
class SerialReaderThread(QThread):
    data_received = pyqtSignal(bytes)

    def __init__(self, port, baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=0.1):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.serial = None
        self._running = False

    def run(self):
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=self.timeout
            )
            self._running = True
            while self._running:
                if self.serial.in_waiting:
                    data = self.serial.read(self.serial.in_waiting)
                    if data:
                        self.data_received.emit(data)
                self.msleep(10)
        except Exception as e:
            self.data_received.emit(f"ERROR: {e}".encode())
        finally:
            if self.serial and self.serial.is_open:
                self.serial.close()

    def stop(self):
        self._running = False
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.quit()
        self.wait()

    def write(self, data: bytes):
        if self.serial and self.serial.is_open:
            self.serial.write(data)
            return True
        return False


# ========================== Configuration Dialog ==========================
class ConfigDialog(QDialog):
    def __init__(self, parent=None, port=None, baudrate=9600, main_window=None):
        super().__init__(parent)
        self.setWindowTitle("JDY-41 Configuration")
        self.setModal(True)
        self.resize(700, 600)

        self.port = port
        self.baudrate = baudrate
        self.main_window = main_window
        self.read_thread = None
        self.profiles_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles.json")
        self.profiles = []  # список словарей {name, baud, channel, power, clss, id, ack}

        self.init_ui()
        self.load_profiles()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # ---- Верхняя часть: параметры ----
        grid_layout = QGridLayout()

        grid_layout.addWidget(QLabel("Baud Rate:"), 0, 0)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["1200", "2400", "4800", "9600", "19200", "38400"])
        self.baud_combo.setCurrentText("9600")
        grid_layout.addWidget(self.baud_combo, 0, 1)

        grid_layout.addWidget(QLabel("Channel (0-127):"), 1, 0)
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(0, 127)
        self.channel_spin.setValue(0)
        grid_layout.addWidget(self.channel_spin, 1, 1)

        grid_layout.addWidget(QLabel("Tx Power:"), 2, 0)
        self.power_combo = QComboBox()
        power_items = [
            ("+12 dBm", 0x09),
            ("-10 dBm", 0x08),
            ("-9 dBm",  0x07),
            ("-6 dBm",  0x06),
            ("-3 dBm",  0x05),
            ("0 dBm",   0x04),
            ("-5 dBm",  0x03),
            ("-15 dBm", 0x02),
            ("-25 dBm", 0x01),
        ]
        for label, code in power_items:
            self.power_combo.addItem(label, code)
        self.power_combo.setCurrentIndex(0)
        grid_layout.addWidget(self.power_combo, 2, 1)

        grid_layout.addWidget(QLabel("CLSS Mode:"), 3, 0)
        self.clss_combo = QComboBox()
        clss_items = [
            ("Transparent (A0)", 0xA0),
            ("Remote TX with LED (C0)", 0xC0),
            ("Remote TX (C1)", 0xC1),
            ("Non-learning RX sync (C2)", 0xC2),
            ("Non-learning RX reverse (C3)", 0xC3),
            ("Non-learning RX pulse (C4)", 0xC4),
            ("Learning RX sync (C5)", 0xC5),
            ("Learning RX reverse (C6)", 0xC6),
            ("Learning RX pulse (C7)", 0xC7),
        ]
        for label, code in clss_items:
            self.clss_combo.addItem(label, code)
        self.clss_combo.setCurrentIndex(0)
        grid_layout.addWidget(self.clss_combo, 3, 1)

        grid_layout.addWidget(QLabel("Device ID (HEX, 8 digits):"), 4, 0)
        id_layout = QHBoxLayout()
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("e.g. 66778855")
        self.id_edit.setText("66778855")
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self.generate_id)
        id_layout.addWidget(self.id_edit)
        id_layout.addWidget(self.generate_btn)
        grid_layout.addLayout(id_layout, 4, 1)

        grid_layout.addWidget(QLabel("ACK Response:"), 5, 0)
        self.ack_combo = QComboBox()
        self.ack_combo.addItem("Disabled", 0)
        self.ack_combo.addItem("Enabled", 1)
        self.ack_combo.setCurrentIndex(1)
        grid_layout.addWidget(self.ack_combo, 5, 1)

        main_layout.addLayout(grid_layout)

        # ---- Кнопки: Read, Save, Delete, OK+Reset, OK, Cancel ----
        button_layout = QHBoxLayout()
        self.read_params_btn = QPushButton("Read Parameters")
        self.read_params_btn.clicked.connect(self.read_parameters)
        button_layout.addWidget(self.read_params_btn)

        self.save_profile_btn = QPushButton("Сохранить")
        self.save_profile_btn.clicked.connect(self.save_profile)
        button_layout.addWidget(self.save_profile_btn)

        self.delete_profile_btn = QPushButton("Удалить")
        self.delete_profile_btn.clicked.connect(self.delete_profile)
        button_layout.addWidget(self.delete_profile_btn)

        button_layout.addStretch()

        self.ok_reset_btn = QPushButton("OK+Reset")
        self.ok_reset_btn.clicked.connect(self.accept_with_reset)
        button_layout.addWidget(self.ok_reset_btn)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        button_layout.addWidget(self.button_box)

        main_layout.addLayout(button_layout)

        # ---- Таблица сохранённых профилей ----
        table_label = QLabel("Saved Profiles:")
        main_layout.addWidget(table_label)

        self.profile_table = QTableWidget()
        self.profile_table.setColumnCount(7)
        self.profile_table.setHorizontalHeaderLabels(["Name", "Baud", "Ch", "Power", "CLSS", "ID", "ACK"])
        self.profile_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.profile_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.profile_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.profile_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.profile_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.profile_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.profile_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.profile_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.profile_table.setSelectionMode(QTableWidget.SingleSelection)
        self.profile_table.itemSelectionChanged.connect(self.on_profile_selected)
        main_layout.addWidget(self.profile_table)

        # Статусная строка
        self.status_label = QLabel("")
        main_layout.addWidget(self.status_label)

    # ---------- Генерация ID ----------
    def generate_id(self):
        rand_int = random.randint(0x00000001, 0xFFFFFFFF)
        id_hex = f"{rand_int:08X}"
        self.id_edit.setText(id_hex)

    # ---------- Работа с профилями ----------
    def load_profiles(self):
        if os.path.exists(self.profiles_file):
            try:
                with open(self.profiles_file, 'r', encoding='utf-8') as f:
                    self.profiles = json.load(f)
            except Exception as e:
                self.profiles = []
        else:
            self.profiles = []
        self.update_table()

    def save_profiles_to_file(self):
        try:
            with open(self.profiles_file, 'w', encoding='utf-8') as f:
                json.dump(self.profiles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save profiles:\n{str(e)}")

    def update_table(self):
        self.profile_table.setRowCount(len(self.profiles))
        for row, prof in enumerate(self.profiles):
            self.profile_table.setItem(row, 0, QTableWidgetItem(prof.get('name', '')))
            self.profile_table.setItem(row, 1, QTableWidgetItem(str(prof.get('baud', ''))))
            self.profile_table.setItem(row, 2, QTableWidgetItem(str(prof.get('channel', ''))))
            power_label = self.get_power_label(prof.get('power', 0x09))
            self.profile_table.setItem(row, 3, QTableWidgetItem(power_label))
            clss_label = self.get_clss_label(prof.get('clss', 0xA0))
            self.profile_table.setItem(row, 4, QTableWidgetItem(clss_label))
            self.profile_table.setItem(row, 5, QTableWidgetItem(prof.get('id', '')))
            ack_label = "Enabled" if prof.get('ack', 1) == 1 else "Disabled"
            self.profile_table.setItem(row, 6, QTableWidgetItem(ack_label))

    def get_power_label(self, power_code):
        power_map = {
            0x09: "+12 dBm", 0x08: "-10 dBm", 0x07: "-9 dBm", 0x06: "-6 dBm",
            0x05: "-3 dBm", 0x04: "0 dBm", 0x03: "-5 dBm", 0x02: "-15 dBm", 0x01: "-25 dBm"
        }
        return power_map.get(power_code, "Unknown")

    def get_clss_label(self, clss_code):
        clss_map = {
            0xA0: "Transparent (A0)",
            0xC0: "Remote TX LED (C0)",
            0xC1: "Remote TX (C1)",
            0xC2: "Non-learning RX sync (C2)",
            0xC3: "Non-learning RX reverse (C3)",
            0xC4: "Non-learning RX pulse (C4)",
            0xC5: "Learning RX sync (C5)",
            0xC6: "Learning RX reverse (C6)",
            0xC7: "Learning RX pulse (C7)"
        }
        return clss_map.get(clss_code, "Unknown")

    def save_profile(self):
        name, ok = QInputDialog.getText(self, "Сохранить профиль", "Введите имя профиля:")
        if not ok or not name.strip():
            return
        name = name.strip()

        # Проверим, нет ли уже профиля с таким именем
        for p in self.profiles:
            if p.get('name', '').lower() == name.lower():
                reply = QMessageBox.question(self, "Перезаписать?",
                                             f"Профиль '{name}' уже существует. Перезаписать?",
                                             QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No:
                    return
                self.profiles = [p for p in self.profiles if p.get('name', '').lower() != name.lower()]
                break

        # Собираем параметры
        baud = self.baud_combo.currentText()
        channel = self.channel_spin.value()
        power = self.power_combo.currentData()
        clss = self.clss_combo.currentData()
        dev_id = self.id_edit.text().strip()
        ack = self.ack_combo.currentData()

        if len(dev_id) != 8 or not all(c in '0123456789ABCDEFabcdef' for c in dev_id):
            QMessageBox.warning(self, "Неверный ID", "Device ID должен содержать 8 шестнадцатеричных цифр.")
            return

        new_profile = {
            'name': name,
            'baud': baud,
            'channel': channel,
            'power': power,
            'clss': clss,
            'id': dev_id,
            'ack': ack
        }
        self.profiles.append(new_profile)
        self.save_profiles_to_file()
        self.update_table()
        self.status_label.setText(f"Профиль '{name}' сохранён.")

    def delete_profile(self):
        selected = self.profile_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Удаление", "Выберите профиль для удаления.")
            return
        row = selected[0].row()
        if row < 0 or row >= len(self.profiles):
            return
        prof_name = self.profiles[row].get('name', '')
        reply = QMessageBox.question(self, "Удалить профиль",
                                     f"Удалить профиль '{prof_name}'?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        del self.profiles[row]
        self.save_profiles_to_file()
        self.update_table()
        self.status_label.setText(f"Профиль '{prof_name}' удалён.")

    def on_profile_selected(self):
        selected = self.profile_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        if row < 0 or row >= len(self.profiles):
            return
        prof = self.profiles[row]
        self.baud_combo.setCurrentText(prof.get('baud', '9600'))
        self.channel_spin.setValue(prof.get('channel', 0))
        power_code = prof.get('power', 0x09)
        idx = self.power_combo.findData(power_code)
        if idx >= 0:
            self.power_combo.setCurrentIndex(idx)
        clss_code = prof.get('clss', 0xA0)
        idx = self.clss_combo.findData(clss_code)
        if idx >= 0:
            self.clss_combo.setCurrentIndex(idx)
        self.id_edit.setText(prof.get('id', '66778855'))
        ack_val = prof.get('ack', 1)
        idx = self.ack_combo.findData(ack_val)
        if idx >= 0:
            self.ack_combo.setCurrentIndex(idx)
        self.status_label.setText(f"Загружен профиль '{prof.get('name', '')}'")

    # ---------- Чтение параметров ----------
    def read_parameters(self):
        if not self.port:
            QMessageBox.warning(self, "Error", "No COM port selected in main window.")
            return

        was_connected = False
        if self.main_window and self.main_window.is_connected:
            was_connected = True
            self.main_window.disconnect_from_port(silent=True)
            QApplication.processEvents()
            loop = QEventLoop()
            QTimer.singleShot(200, loop.quit)
            loop.exec_()

        self.read_params_btn.setEnabled(False)
        self.button_box.setEnabled(False)
        self.ok_reset_btn.setEnabled(False)
        self.save_profile_btn.setEnabled(False)
        self.delete_profile_btn.setEnabled(False)
        self.status_label.setText("Reading parameters...")
        QApplication.processEvents()

        cmd = bytes([0xAA, 0xE2, 0x0D, 0x0A])

        temp_thread = SerialReaderThread(self.port, baudrate=self.baudrate, timeout=1.0)
        response_received = False
        response_data = b''

        def on_data(data):
            nonlocal response_received, response_data
            response_data += data
            if len(response_data) >= 12:
                if response_data[0:2] == b'\xAA\xE2':
                    response_received = True

        temp_thread.data_received.connect(on_data)
        temp_thread.start()

        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec_()

        temp_thread.write(cmd)

        loop = QEventLoop()
        QTimer.singleShot(3000, loop.quit)
        check_timer = QTimer()
        check_timer.timeout.connect(lambda: loop.quit() if response_received else None)
        check_timer.start(100)
        loop.exec_()
        check_timer.stop()

        temp_thread.stop()
        temp_thread.deleteLater()

        self.read_params_btn.setEnabled(True)
        self.button_box.setEnabled(True)
        self.ok_reset_btn.setEnabled(True)
        self.save_profile_btn.setEnabled(True)
        self.delete_profile_btn.setEnabled(True)

        if response_received and len(response_data) >= 12:
            try:
                if response_data[0] != 0xAA or response_data[1] != 0xE2:
                    raise ValueError("Invalid header")
                baud_byte = response_data[2]
                channel = response_data[3]
                power_byte = response_data[4]
                clss_byte = response_data[5]
                id_bytes = response_data[6:10]
                ack_byte = response_data[10]

                baud_map_rev = {1: "1200", 2: "2400", 3: "4800", 4: "9600", 5: "19200", 6: "38400"}
                if baud_byte in baud_map_rev:
                    self.baud_combo.setCurrentText(baud_map_rev[baud_byte])
                else:
                    self.status_label.setText(f"Unknown baud code: {baud_byte}")

                self.channel_spin.setValue(channel)

                power_index = self.power_combo.findData(power_byte)
                if power_index >= 0:
                    self.power_combo.setCurrentIndex(power_index)

                clss_index = self.clss_combo.findData(clss_byte)
                if clss_index >= 0:
                    self.clss_combo.setCurrentIndex(clss_index)

                id_hex = id_bytes.hex().upper()
                self.id_edit.setText(id_hex)

                ack_index = self.ack_combo.findData(ack_byte)
                if ack_index >= 0:
                    self.ack_combo.setCurrentIndex(ack_index)

                self.status_label.setText("Parameters read successfully")
            except Exception as e:
                self.status_label.setText(f"Parse error: {str(e)}")
                QMessageBox.warning(self, "Parse Error", f"Failed to parse response:\n{str(e)}")
        else:
            self.status_label.setText("No response or invalid response")
            QMessageBox.warning(self, "Read Failed",
                                "Could not read parameters.\n"
                                "Make sure the module is in configuration mode (CS and SET low)\n"
                                "and the correct COM port and baud rate are selected.")

        if was_connected:
            new_baud = int(self.baud_combo.currentText()) if self.baud_combo.currentText().isdigit() else self.baudrate
            self.main_window.baud_combo.setCurrentText(str(new_baud))
            self.main_window.connect_to_port(baudrate=new_baud)

    # ---------- Получение байтов конфигурации ----------
    def get_config_bytes(self):
        baud_map = {"1200": 1, "2400": 2, "4800": 3, "9600": 4, "19200": 5, "38400": 6}
        baud_byte = baud_map[self.baud_combo.currentText()]
        channel = self.channel_spin.value()
        power_byte = self.power_combo.currentData()
        clss_byte = self.clss_combo.currentData()
        id_str = self.id_edit.text().strip()
        if len(id_str) != 8:
            raise ValueError("Device ID must be exactly 8 hexadecimal digits.")
        try:
            id_bytes = bytes.fromhex(id_str)
        except ValueError:
            raise ValueError("Invalid hexadecimal format for Device ID.")
        ack_byte = self.ack_combo.currentData()
        cmd = bytearray([0xA9, 0xE1, baud_byte, channel, power_byte, clss_byte])
        cmd.extend(id_bytes)
        cmd.extend([ack_byte, 0x00, 0x0D, 0x0A])
        return bytes(cmd)

    # ---------- Слот для OK (переопределён) ----------
    def accept(self):
        try:
            config_cmd = self.get_config_bytes()
            if self.main_window:
                self.main_window.send_raw_data(config_cmd)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return
        super().accept()

    # ---------- Слот для OK+Reset ----------
    def accept_with_reset(self):
        try:
            config_cmd = self.get_config_bytes()
            if self.main_window:
                self.main_window.send_raw_data(config_cmd)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return

        QApplication.processEvents()
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec_()

        reset_cmd = bytes([0xAB, 0xE3, 0x0D, 0x0A])
        if self.main_window:
            self.main_window.send_raw_data(reset_cmd)

        QApplication.processEvents()
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec_()

        if self.main_window and self.main_window.is_connected:
            new_baud = int(self.baud_combo.currentText()) if self.baud_combo.currentText().isdigit() else self.baudrate
            self.main_window.baud_combo.setCurrentText(str(new_baud))
            self.main_window.disconnect_from_port(silent=True)
            QApplication.processEvents()
            loop = QEventLoop()
            QTimer.singleShot(200, loop.quit)
            loop.exec_()
            self.main_window.connect_to_port(baudrate=new_baud)

        super().accept()


# ========================== Main Window ==========================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JDY-41 Configuration Tool")
        self.setMinimumSize(900, 700)

        self.reader_thread = None
        self.is_connected = False
        self.log_entries = []
        self.auto_detect_running = False
        self.reconnecting = False
        self.reconnect_timer = None

        self.rx_buffer = b''
        self.rx_timer = QTimer()
        self.rx_timer.setSingleShot(True)
        self.rx_timer.timeout.connect(self.flush_rx_buffer)

        self.init_ui()
        self.refresh_ports()
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_ports)
        self.timer.start(5000)

    def init_ui(self):
        menubar = self.menuBar()

        # Меню "Модуль"
        module_menu = menubar.addMenu("Модуль")

        config_action = QAction("Конфигурация...", self)
        config_action.triggered.connect(self.open_config_dialog)
        module_menu.addAction(config_action)

        module_menu.addSeparator()

        reset_action = QAction("Сброс", self)
        reset_action.triggered.connect(self.send_reset)
        module_menu.addAction(reset_action)

        version_action = QAction("Чтение версии", self)
        version_action.triggered.connect(self.send_version)
        module_menu.addAction(version_action)

        read_params_action = QAction("Чтение параметров", self)
        read_params_action.triggered.connect(self.send_read_params)
        module_menu.addAction(read_params_action)

        module_menu.addSeparator()

        set_id_action = QAction("Установить ID...", self)
        set_id_action.triggered.connect(self.open_set_id_dialog)
        module_menu.addAction(set_id_action)

        # Меню "Справка"
        help_menu = menubar.addMenu("Справка")

        diagram_action = QAction("Схема подключения", self)
        diagram_action.triggered.connect(self.show_connection_diagram)
        help_menu.addAction(diagram_action)

        datasheet_action = QAction("Datasheet (PDF)", self)
        datasheet_action.triggered.connect(self.open_datasheet)
        help_menu.addAction(datasheet_action)

        help_menu.addSeparator()

        about_action = QAction("О программе", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        top_layout = QHBoxLayout()

        # ---- COM Port ----
        port_group = QGroupBox("COM Port")
        port_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(120)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        port_layout.addWidget(QLabel("Port:"))
        port_layout.addWidget(self.port_combo)
        port_layout.addWidget(self.refresh_btn)
        port_layout.addWidget(self.connect_btn)
        port_group.setLayout(port_layout)
        top_layout.addWidget(port_group)

        # ---- Baud Rate ----
        baud_group = QGroupBox("Baud Rate")
        baud_layout = QHBoxLayout()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"])
        self.baud_combo.setCurrentText("9600")
        self.baud_combo.currentIndexChanged.connect(self.on_baud_changed)

        self.auto_detect_btn = QPushButton("Auto Detect")
        self.auto_detect_btn.clicked.connect(self.auto_detect_baudrate)
        baud_layout.addWidget(QLabel("Speed:"))
        baud_layout.addWidget(self.baud_combo)
        baud_layout.addWidget(self.auto_detect_btn)
        baud_group.setLayout(baud_layout)
        top_layout.addWidget(baud_group)

        # ---- Module ----
        module_group = QGroupBox("Module")
        module_layout = QHBoxLayout()
        self.config_btn = QPushButton("Configure...")
        self.config_btn.clicked.connect(self.open_config_dialog)
        module_layout.addWidget(self.config_btn)
        module_group.setLayout(module_layout)
        top_layout.addWidget(module_group)

        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # ---- Log ----
        log_group = QGroupBox("Communication Log")
        log_layout = QVBoxLayout()

        log_toolbar = QHBoxLayout()
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_toolbar.addStretch()
        log_toolbar.addWidget(self.clear_log_btn)

        log_layout.addLayout(log_toolbar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group, 1)

        # ---- Command ----
        cmd_group = QGroupBox("Send Command")
        cmd_layout = QHBoxLayout()

        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Enter command (ASCII or HEX)")
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_command)
        self.cmd_input.returnPressed.connect(self.send_command)

        self.hex_mode_cb = QCheckBox("HEX input")
        self.hex_mode_cb.toggled.connect(self.on_hex_input_toggled)

        cmd_layout.addWidget(QLabel("Command:"))
        cmd_layout.addWidget(self.cmd_input, 1)
        cmd_layout.addWidget(self.hex_mode_cb)
        cmd_layout.addWidget(self.send_btn)

        cmd_group.setLayout(cmd_layout)
        main_layout.addWidget(cmd_group)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Disconnected")

        self.apply_stylesheet()

    def apply_stylesheet(self):
        style = """
            QMainWindow { background-color: #f0f0f0; }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #aaaaaa;
                border-radius: 4px;
                padding: 5px 10px;
            }
            QPushButton:hover { background-color: #d0d0d0; }
            QPushButton:pressed { background-color: #c0c0c0; }
            QPushButton#connect_btn_connected {
                background-color: #4caf50;
                color: white;
            }
            QPushButton#connect_btn_connected:hover { background-color: #45a049; }
            QPushButton#connect_btn_disconnected {
                background-color: #f44336;
                color: white;
            }
            QPushButton#connect_btn_disconnected:hover { background-color: #da190b; }
            QTextEdit {
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: white;
                font-family: Consolas, monospace;
            }
            QComboBox, QLineEdit {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 3px;
            }
            QRadioButton, QCheckBox { spacing: 5px; }
            QTableWidget {
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: white;
                gridline-color: #d0d0d0;
            }
            QHeaderView::section {
                background-color: #e8e8e8;
                padding: 4px;
                border: 1px solid #cccccc;
                font-weight: bold;
            }
        """
        self.setStyleSheet(style)

    # ---------- Port management ----------
    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)
        index = self.port_combo.findText(current)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)

    def toggle_connection(self):
        if not self.is_connected:
            self.connect_to_port()
        else:
            self.disconnect_from_port()

    def connect_to_port(self, baudrate=None):
        if self.reconnecting or self.is_connected:
            return

        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Error", "No COM port selected.")
            return

        if baudrate is None:
            baudrate = int(self.baud_combo.currentText())

        self.reconnecting = True
        try:
            if self.reader_thread:
                self.reader_thread.stop()
                self.reader_thread = None

            self.reader_thread = SerialReaderThread(port, baudrate=baudrate)
            self.reader_thread.data_received.connect(self.on_data_received)
            self.reader_thread.start()
            self.is_connected = True
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setObjectName("connect_btn_connected")
            self.status_bar.showMessage(f"Connected to {port} at {baudrate} baud")
            self.log_message("System", f"Connected to {port} at {baudrate} baud")
            self.apply_stylesheet()
        except Exception as e:
            self.is_connected = False
            self.connect_btn.setText("Connect")
            self.connect_btn.setObjectName("connect_btn_disconnected")
            self.status_bar.showMessage("Disconnected")
            QMessageBox.critical(self, "Connection Error", f"Failed to open port:\n{str(e)}")
            self.apply_stylesheet()
        finally:
            self.reconnecting = False

    def disconnect_from_port(self, silent=False):
        if self.reader_thread:
            self.reader_thread.stop()
            self.reader_thread = None
        self.is_connected = False
        self.connect_btn.setText("Connect")
        self.connect_btn.setObjectName("connect_btn_disconnected")
        self.status_bar.showMessage("Disconnected")
        if not silent:
            self.log_message("System", "Disconnected")
        self.apply_stylesheet()

    # ---------- Auto Detect Baudrate ----------
    def auto_detect_baudrate(self):
        if self.auto_detect_running:
            return
        self.auto_detect_running = True
        self.set_ui_enabled(False)

        if self.is_connected:
            self.disconnect_from_port(silent=True)

        self.status_bar.showMessage("Auto-detecting baud rate...")
        self.log_message("AutoDetect", "Starting baud rate auto-detection...")

        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Error", "No COM port selected.")
            self.set_ui_enabled(True)
            self.auto_detect_running = False
            return

        baud_rates = [int(self.baud_combo.itemText(i)) for i in range(self.baud_combo.count())]
        found_baud = None
        version_cmd = bytes([0xAB, 0xCD, 0x0D, 0x0A])

        for baud in baud_rates:
            self.status_bar.showMessage(f"Trying {baud} baud...")
            self.log_message("AutoDetect", f"Testing baud rate {baud}")
            QApplication.processEvents()

            temp_thread = SerialReaderThread(port, baudrate=baud, timeout=0.5)
            response_received = False
            response_data = b''

            def on_data(data):
                nonlocal response_received, response_data
                response_data += data
                if b'+V' in response_data:
                    response_received = True

            temp_thread.data_received.connect(on_data)
            temp_thread.start()
            loop = QEventLoop()
            QTimer.singleShot(200, loop.quit)
            loop.exec_()

            for _ in range(2):
                if response_received:
                    break
                temp_thread.write(version_cmd)
                loop = QEventLoop()
                QTimer.singleShot(200, loop.quit)
                loop.exec_()

            loop = QEventLoop()
            QTimer.singleShot(3000, loop.quit)
            check_timer = QTimer()
            check_timer.timeout.connect(lambda: loop.quit() if response_received else None)
            check_timer.start(100)
            loop.exec_()
            check_timer.stop()

            temp_thread.stop()
            temp_thread.deleteLater()

            if response_received:
                found_baud = baud
                self.log_message("AutoDetect", f"Found baud rate: {baud}")
                break
            else:
                self.log_message("AutoDetect", f"No response at {baud}")

        self.set_ui_enabled(True)
        self.auto_detect_running = False

        if found_baud:
            self.baud_combo.setCurrentText(str(found_baud))
            self.status_bar.showMessage(f"Auto-detected baud rate: {found_baud}")
            self.log_message("System", f"Auto-detected baud rate: {found_baud}")
            self.connect_to_port(baudrate=found_baud)
        else:
            QMessageBox.information(self, "Auto Detect",
                                    "Could not detect baud rate.\n"
                                    "Please make sure the module is in configuration mode (CS and SET low)\n"
                                    "and try again.")
            self.status_bar.showMessage("Auto-detect failed")
            self.log_message("System", "Auto-detect failed - no response on any baud rate")

    def set_ui_enabled(self, enabled):
        self.connect_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        self.auto_detect_btn.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.cmd_input.setEnabled(enabled)
        self.port_combo.setEnabled(enabled)
        self.baud_combo.setEnabled(enabled)
        self.config_btn.setEnabled(enabled)
        for action in self.menuBar().actions():
            action.setEnabled(enabled)

    # ---------- Обработчик изменения скорости ----------
    def on_baud_changed(self):
        if self.reconnecting:
            return
        if self.is_connected:
            if self.reconnect_timer:
                self.reconnect_timer.stop()
                self.reconnect_timer = None
            self.log_message("System", f"Baud rate changed to {self.baud_combo.currentText()}, reconnecting...")
            self.disconnect_from_port(silent=True)
            self.reconnect_timer = QTimer()
            self.reconnect_timer.setSingleShot(True)
            self.reconnect_timer.timeout.connect(self._do_reconnect)
            self.reconnect_timer.start(300)

    def _do_reconnect(self):
        self.reconnect_timer = None
        self.connect_to_port()

    # ---------- Data handling ----------
    def on_data_received(self, data):
        if isinstance(data, bytes):
            self.rx_buffer += data
            self.rx_timer.start(100)
        else:
            self.log_message("Error", data)

    def flush_rx_buffer(self):
        if self.rx_buffer:
            self.log_message("RX", self.rx_buffer)
            self.rx_buffer = b''

    def send_raw_data(self, data: bytes):
        if not self.is_connected or not self.reader_thread:
            QMessageBox.warning(self, "Error", "Not connected to serial port.")
            return False
        if self.reader_thread.write(data):
            self.log_message("TX", data)
            return True
        else:
            QMessageBox.critical(self, "Error", "Failed to write to serial port.")
            return False

    def send_command(self):
        cmd_text = self.cmd_input.text().strip()
        if not cmd_text:
            return
        if self.hex_mode_cb.isChecked():
            hex_str = cmd_text.replace(" ", "")
            try:
                if len(hex_str) % 2 != 0:
                    raise ValueError("Odd length HEX string")
                data = bytes.fromhex(hex_str)
            except ValueError as e:
                QMessageBox.warning(self, "Invalid HEX", f"HEX conversion error:\n{e}")
                return
        else:
            data = cmd_text.encode('utf-8')
        if self.send_raw_data(data):
            self.cmd_input.clear()

    def log_message(self, direction, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.log_entries.append((direction, data))
        self.update_log_display()

    def update_log_display(self):
        self.log_text.clear()
        for direction, data in self.log_entries:
            if direction in ("System", "Error", "AutoDetect"):
                prefix = f"[{direction}] "
                display_str = data.decode('utf-8', errors='replace')
            else:
                prefix = f"[{direction}] "
                if direction == "TX":
                    display_str = ' '.join(f'{b:02X}' for b in data)
                else:  # RX
                    printable = True
                    for b in data:
                        if b not in (0x0D, 0x0A) and (b < 32 or b > 126):
                            printable = False
                            break
                    if printable:
                        display_str = data.decode('utf-8', errors='replace')
                    else:
                        display_str = ' '.join(f'{b:02X}' for b in data)
            self.log_text.append(prefix + display_str)
        self.log_text.moveCursor(QTextCursor.End)

    def on_hex_input_toggled(self, checked):
        if checked:
            self.cmd_input.setPlaceholderText("Enter HEX (e.g., AA BB 0D 0A)")
        else:
            self.cmd_input.setPlaceholderText("Enter ASCII text")

    def clear_log(self):
        self.log_entries.clear()
        self.log_text.clear()
        self.rx_buffer = b''
        self.rx_timer.stop()

    # ---------- Menu actions ----------
    def open_config_dialog(self):
        dialog = ConfigDialog(self,
                              port=self.port_combo.currentText(),
                              baudrate=int(self.baud_combo.currentText()),
                              main_window=self)
        if dialog.exec_() == QDialog.Accepted:
            pass

    def send_reset(self):
        self.send_raw_data(bytes([0xAB, 0xE3, 0x0D, 0x0A]))

    def send_version(self):
        self.send_raw_data(bytes([0xAB, 0xCD, 0x0D, 0x0A]))

    def send_read_params(self):
        self.send_raw_data(bytes([0xAA, 0xE2, 0x0D, 0x0A]))

    def open_set_id_dialog(self):
        id_str, ok = QInputDialog.getText(self, "Set Device ID",
                                          "Enter new Device ID (8 hex digits):",
                                          text="11223344")
        if ok and id_str:
            id_str = id_str.strip()
            if len(id_str) != 8:
                QMessageBox.warning(self, "Invalid ID", "ID must be exactly 8 hex digits.")
                return
            try:
                id_bytes = bytes.fromhex(id_str)
            except ValueError:
                QMessageBox.warning(self, "Invalid ID", "Invalid hex format.")
                return
            cmd = bytearray([0xF1, 0xAE])
            cmd.extend(id_bytes)
            cmd.extend([0x0D, 0x0A])
            self.send_raw_data(bytes(cmd))

    # ---------- Справка ----------
    def show_connection_diagram(self):
        image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "con.png")
        if not os.path.exists(image_path):
            QMessageBox.warning(self, "Ошибка", f"Файл схемы не найден:\n{image_path}")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Схема подключения JDY-41")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        label = QLabel()
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось загрузить изображение.")
            dialog.close()
            return

        if pixmap.width() > 800 or pixmap.height() > 600:
            pixmap = pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignCenter)

        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)

        layout.addWidget(scroll)

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        dialog.resize(850, 650)
        dialog.exec_()

    def open_datasheet(self):
        pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jdy-41-manual.pdf")
        if not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Ошибка", f"Файл даташита не найден:\n{pdf_path}")
            return

        url = QUrl.fromLocalFile(pdf_path)
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть PDF-файл. Убедитесь, что установлена программа для просмотра PDF.")

    def show_about(self):
        QMessageBox.about(self, "О программе",
                          "Программа разработана для упрощения работы с модулем JDY-41.\n\n"
                          "Разработчик: DennyK\n"
                          "Год: 2026")

    def closeEvent(self, event):
        if self.reader_thread:
            self.reader_thread.stop()
        event.accept()


# ========================== Main entry ==========================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())