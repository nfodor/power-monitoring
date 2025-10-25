#!/usr/bin/env python3
"""
Edge Cloud Worker Monitor
Automatically detects WireGuard interface and notifies bypass server of status changes
"""

import json
import os
import socket
import subprocess
import time
import requests
import secrets
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BypassNotifier:
    def __init__(self, config_file="/home/pi/dev/power/bypass_config.json"):
        self.config_file = config_file
        self.config = self.load_or_create_config()
        self.last_wg_status = None
        self.battery_runtime_start = None
        
    def load_or_create_config(self) -> Dict:
        """Load existing config or create new one"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                logger.info(f"Loaded existing config for unit {config.get('unit_id')}")
                return config
            except Exception as e:
                logger.error(f"Error loading config: {e}")
        
        # Create new config
        config = {
            "unit_id": self.generate_unit_id(),
            "auth_key": self.generate_auth_key(),
            "bypass_servers": [
                {
                    "url": "http://10.0.0.1:8080",
                    "priority": 1,
                    "enabled": True,
                    "registration_status": "pending",
                    "last_success": None,
                    "last_error": None,
                    "total_notifications": 0,
                    "success_count": 0
                },
                {
                    "url": "http://172.16.0.1:8080", 
                    "priority": 2,
                    "enabled": True,
                    "registration_status": "pending",
                    "last_success": None,
                    "last_error": None,
                    "total_notifications": 0,
                    "success_count": 0
                },
                {
                    "url": "http://192.168.1.1:8080",
                    "priority": 3,
                    "enabled": True,
                    "registration_status": "pending", 
                    "last_success": None,
                    "last_error": None,
                    "total_notifications": 0,
                    "success_count": 0
                }
            ],
            "health_heartbeat_interval": 60,  # seconds
            "notification_timeout": 5,        # seconds
            "max_retry_attempts": 3,
            "created": datetime.utcnow().isoformat(),
            "last_health_broadcast": None
        }
        
        self.save_config(config)
        logger.info(f"Created new config for unit {config['unit_id']}")
        return config
    
    def save_config(self, config: Dict):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def generate_unit_id(self) -> str:
        """Generate stable unit ID based on hostname and MAC address"""
        try:
            hostname = socket.gethostname()
            # Get MAC address from eth0 or wlan0
            for interface in ['eth0', 'wlan0', 'wg0']:
                try:
                    result = subprocess.run(['cat', f'/sys/class/net/{interface}/address'], 
                                          capture_output=True, text=True)
                    if result.returncode == 0:
                        mac = result.stdout.strip().replace(':', '')
                        return f"ups_{hostname}_{mac[-6:]}"
                except:
                    continue
            
            # Fallback to hostname only
            return f"ups_{hostname}_{secrets.token_hex(3)}"
        except Exception as e:
            logger.error(f"Error generating unit ID: {e}")
            return f"ups_unknown_{secrets.token_hex(6)}"
    
    def generate_auth_key(self) -> str:
        """Generate secure authentication key"""
        return secrets.token_urlsafe(32)
    
    def get_wireguard_status(self) -> Dict:
        """Check WireGuard interface status and get details"""
        try:
            # Check if wg0 interface exists and is up
            result = subprocess.run(['ip', 'addr', 'show', 'wg0'], 
                                  capture_output=True, text=True)
            
            if result.returncode != 0:
                return {"interface_up": False, "error": "Interface not found"}
            
            output = result.stdout
            
            # Extract IP address
            local_ip = None
            for line in output.split('\n'):
                if 'inet ' in line and not '127.0.0.1' in line:
                    local_ip = line.strip().split()[1].split('/')[0]
                    break
            
            # Check if interface is UP
            interface_up = 'state UP' in output or 'UP,' in output
            
            # Get peer information
            peer_info = self.get_wireguard_peer_info()
            
            return {
                "interface_up": interface_up,
                "local_ip": local_ip,
                "peer_endpoint": peer_info.get("endpoint"),
                "last_handshake": peer_info.get("last_handshake"),
                "transfer_rx": peer_info.get("transfer_rx"),
                "transfer_tx": peer_info.get("transfer_tx")
            }
            
        except Exception as e:
            logger.error(f"Error checking WireGuard status: {e}")
            return {"interface_up": False, "error": str(e)}
    
    def get_wireguard_peer_info(self) -> Dict:
        """Get WireGuard peer information"""
        try:
            result = subprocess.run(['wg', 'show', 'wg0'], 
                                  capture_output=True, text=True)
            
            if result.returncode != 0:
                return {}
            
            peer_info = {}
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('endpoint:'):
                    peer_info["endpoint"] = line.split(':', 1)[1].strip()
                elif line.startswith('latest handshake:'):
                    peer_info["last_handshake"] = line.split(':', 1)[1].strip()
                elif line.startswith('transfer:'):
                    transfer = line.split(':', 1)[1].strip()
                    if 'received' in transfer and 'sent' in transfer:
                        parts = transfer.split(',')
                        for part in parts:
                            if 'received' in part:
                                peer_info["transfer_rx"] = part.strip()
                            elif 'sent' in part:
                                peer_info["transfer_tx"] = part.strip()
            
            return peer_info
            
        except Exception as e:
            logger.error(f"Error getting peer info: {e}")
            return {}
    
    def notify_bypass_servers(self, payload: Dict, endpoint: str = "status") -> Dict:
        """Send notification to all enabled bypass servers"""
        headers = {
            "X-UPS-Unit-ID": self.config["unit_id"],
            "X-UPS-Auth-Key": self.config["auth_key"],
            "Content-Type": "application/json"
        }
        
        results = {
            "total_servers": 0,
            "successful": 0,
            "failed": 0,
            "server_results": []
        }
        
        # Get servers sorted by priority
        servers = sorted(self.config["bypass_servers"], key=lambda x: x["priority"])
        
        for server in servers:
            if not server["enabled"]:
                continue
                
            results["total_servers"] += 1
            server_result = {
                "url": server["url"],
                "priority": server["priority"],
                "success": False,
                "response_time": None,
                "error": None,
                "status_code": None
            }
            
            try:
                start_time = time.time()
                url = f"{server['url']}/api/ups/{endpoint}"
                
                response = requests.post(
                    url, 
                    json=payload, 
                    headers=headers, 
                    timeout=self.config.get("notification_timeout", 5)
                )
                
                response_time = time.time() - start_time
                server_result["response_time"] = response_time
                server_result["status_code"] = response.status_code
                
                if response.status_code == 200:
                    server_result["success"] = True
                    results["successful"] += 1
                    
                    # Update server stats
                    server["last_success"] = datetime.utcnow().isoformat()
                    server["success_count"] += 1
                    server["last_error"] = None
                    
                    logger.info(f"✅ Notified {server['url']} ({response_time:.2f}s)")
                else:
                    results["failed"] += 1
                    error_msg = f"HTTP {response.status_code}"
                    server_result["error"] = error_msg
                    server["last_error"] = error_msg
                    logger.warning(f"❌ {server['url']} returned {response.status_code}")
                    
            except requests.exceptions.RequestException as e:
                response_time = time.time() - start_time
                server_result["response_time"] = response_time
                server_result["error"] = str(e)
                results["failed"] += 1
                
                server["last_error"] = str(e)
                logger.debug(f"❌ Failed to reach {server['url']}: {e}")
            
            # Update total notifications counter
            server["total_notifications"] += 1
            results["server_results"].append(server_result)
        
        # Save updated server stats
        self.save_config(self.config)
        
        if results["successful"] > 0:
            logger.info(f"Notified {results['successful']}/{results['total_servers']} bypass servers")
        else:
            logger.error(f"Failed to notify any bypass servers (0/{results['total_servers']})")
        
        return results
    
    def auto_register_with_bypass_servers(self) -> bool:
        """Auto-register with all bypass servers"""
        wg_status = self.get_wireguard_status()
        if not wg_status["interface_up"]:
            logger.warning("WireGuard interface down, cannot register")
            return False
        
        # Prepare registration payload
        payload = {
            "unit_id": self.config["unit_id"],
            "hostname": socket.gethostname(),
            "wireguard_ip": wg_status["local_ip"],
            "auth_key": self.config["auth_key"],
            "capabilities": ["x1200_ups", "power_monitoring", "battery_tracking"],
            "first_contact": datetime.utcnow().isoformat(),
            "health_heartbeat_interval": self.config.get("health_heartbeat_interval", 60)
        }
        
        results = self.notify_bypass_servers(payload, "register")
        
        # Update registration status for successful servers
        for i, server_result in enumerate(results["server_results"]):
            if server_result["success"]:
                self.config["bypass_servers"][i]["registration_status"] = "active"
                logger.info(f"✅ Registered with {server_result['url']}")
            else:
                self.config["bypass_servers"][i]["registration_status"] = "failed"
        
        self.save_config(self.config)
        
        if results["successful"] > 0:
            logger.info(f"Successfully registered with {results['successful']} bypass servers")
            return True
        else:
            logger.warning("Auto-registration failed for all bypass servers")
            return False
    
    def send_status_update(self, power_data: Dict = None) -> bool:
        """Send current status update to bypass server"""
        wg_status = self.get_wireguard_status()
        
        payload = {
            "unit_id": self.config["unit_id"],
            "wireguard_ip": wg_status.get("local_ip"),
            "status": "online" if wg_status["interface_up"] else "offline",
            "timestamp": datetime.utcnow().isoformat(),
            "wireguard_details": {
                "peer_endpoint": wg_status.get("peer_endpoint"),
                "last_handshake": wg_status.get("last_handshake"),
                "interface_up": wg_status["interface_up"]
            }
        }
        
        # Add power data if available
        if power_data:
            payload.update({
                "battery_percent": power_data.get("battery_percent"),
                "battery_voltage": power_data.get("battery_voltage"),
                "external_power": power_data.get("external_power"),
                "estimated_runtime_minutes": power_data.get("estimated_runtime_minutes")
            })
        
        return self.notify_bypass_servers(payload, "status")["successful"] > 0
    
    def monitor_wireguard_status(self, power_data: Dict = None):
        """Monitor WireGuard status and send notifications on changes"""
        current_wg_status = self.get_wireguard_status()
        
        # Check if status changed
        if self.last_wg_status is None or current_wg_status["interface_up"] != self.last_wg_status["interface_up"]:
            
            if current_wg_status["interface_up"] and not (self.last_wg_status and self.last_wg_status["interface_up"]):
                # WireGuard came UP
                logger.info("WireGuard interface came UP - registering with bypass server")
                self.auto_register_with_bypass_servers()
                
            elif not current_wg_status["interface_up"] and (self.last_wg_status and self.last_wg_status["interface_up"]):
                # WireGuard went DOWN
                logger.warning("WireGuard interface went DOWN")
            
            # Send status update
            self.send_status_update(power_data)
            self.last_wg_status = current_wg_status
        
        # Send periodic heartbeat if interface is up
        elif current_wg_status["interface_up"]:
            self.check_and_send_health_heartbeat(power_data)

    def track_battery_runtime(self, power_data: Dict):
        """Track battery runtime and charging cycles"""
        external_power = power_data.get("external_power", True)
        battery_percent = power_data.get("battery_percent", 0)
        
        # Detect start of battery operation (power loss)
        if not external_power and self.battery_runtime_start is None:
            self.battery_runtime_start = datetime.utcnow()
            logger.info("Battery runtime tracking started - external power lost")
            
            # Notify bypass server of power loss
            self.send_power_event("power_lost", power_data)
        
        # Detect end of battery operation (power restored or shutdown)
        elif external_power and self.battery_runtime_start is not None:
            runtime_seconds = (datetime.utcnow() - self.battery_runtime_start).total_seconds()
            runtime_minutes = runtime_seconds / 60
            
            logger.info(f"Battery runtime completed: {runtime_minutes:.1f} minutes")
            
            # Log battery runtime data
            self.log_battery_runtime(runtime_minutes, battery_percent)
            
            # Notify bypass server of power restoration
            self.send_power_event("power_restored", power_data)
            
            self.battery_runtime_start = None
    
    def send_power_event(self, event_type: str, power_data: Dict):
        """Send power-related events to bypass server"""
        payload = {
            "unit_id": self.config["unit_id"],
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "battery_percent": power_data.get("battery_percent"),
            "battery_voltage": power_data.get("battery_voltage"),
            "external_power": power_data.get("external_power")
        }
        
        if event_type == "power_lost" and self.battery_runtime_start:
            payload["battery_runtime_start"] = self.battery_runtime_start.isoformat()
        elif event_type == "power_restored" and self.battery_runtime_start:
            runtime_seconds = (datetime.utcnow() - self.battery_runtime_start).total_seconds()
            payload["battery_runtime_minutes"] = runtime_seconds / 60
        
        self.notify_bypass_servers(payload, "event")
    
    def log_battery_runtime(self, runtime_minutes: float, final_battery_percent: float):
        """Log battery runtime data to CSV file"""
        runtime_log_file = "/home/pi/battery_runtime_log.csv"
        
        # Create header if file doesn't exist
        if not os.path.exists(runtime_log_file):
            with open(runtime_log_file, 'w') as f:
                f.write("Timestamp,Runtime Minutes,Final Battery %,Power Loss Duration,Notes\n")
        
        # Append runtime data
        with open(runtime_log_file, 'a') as f:
            timestamp = datetime.utcnow().isoformat()
            f.write(f"{timestamp},{runtime_minutes:.1f},{final_battery_percent},,Power cycle complete\n")
    
    def get_comprehensive_health_data(self, power_data: Dict = None) -> Dict:
        """Get comprehensive system health data for bypass servers"""
        wg_status = self.get_wireguard_status()
        
        # Base health payload
        health_data = {
            "unit_id": self.config["unit_id"],
            "timestamp": datetime.utcnow().isoformat(),
            "health_type": "heartbeat",
            "wireguard_status": {
                "interface_up": wg_status["interface_up"],
                "local_ip": wg_status.get("local_ip"),
                "peer_endpoint": wg_status.get("peer_endpoint"),
                "last_handshake": wg_status.get("last_handshake"),
                "transfer_rx": wg_status.get("transfer_rx"),
                "transfer_tx": wg_status.get("transfer_tx")
            }
        }
        
        # Add power data if available
        if power_data:
            health_data.update({
                "battery_voltage": power_data.get("battery_voltage"),
                "battery_percentage": power_data.get("battery_percentage"),
                "external_power": power_data.get("external_power"),
                "estimated_runtime_minutes": power_data.get("estimated_runtime_minutes"),
                "cpu_percent": power_data.get("cpu_percent"),
                "cpu_temp": power_data.get("cpu_temp"),
                "memory_percent": power_data.get("memory_percent"),
                "load_avg": power_data.get("load_avg")
            })
        
        # Add system health metrics
        try:
            import psutil
            health_data["system_health"] = {
                "uptime_seconds": time.time() - psutil.boot_time(),
                "disk_usage_percent": psutil.disk_usage('/').percent,
                "network_io": dict(psutil.net_io_counters()._asdict()),
                "process_count": len(psutil.pids())
            }
        except Exception as e:
            health_data["system_health"] = {"error": str(e)}
        
        # Add service status information
        try:
            health_data["services"] = {
                "power_monitor": "active",  # This service is running
                "dashboard": self.check_service_status("power-dashboard.service"),
                "docker": self.check_service_status("docker.service"),
                "ssh": self.check_service_status("ssh.service")
            }
        except Exception as e:
            health_data["services"] = {"error": str(e)}
        
        return health_data
    
    def check_service_status(self, service_name: str) -> str:
        """Check systemd service status"""
        try:
            result = subprocess.run(['systemctl', 'is-active', service_name], 
                                  capture_output=True, text=True)
            return result.stdout.strip()
        except Exception:
            return "unknown"
    
    def check_and_send_health_heartbeat(self, power_data: Dict = None):
        """Check if it's time to send health heartbeat and send if needed"""
        heartbeat_interval = self.config.get("health_heartbeat_interval", 60)
        last_broadcast = self.config.get("last_health_broadcast")
        
        should_send = False
        
        if not last_broadcast:
            should_send = True
        else:
            try:
                last_time = datetime.fromisoformat(last_broadcast.replace('Z', '+00:00'))
                if (datetime.utcnow() - last_time).total_seconds() >= heartbeat_interval:
                    should_send = True
            except Exception:
                should_send = True
        
        if should_send:
            health_data = self.get_comprehensive_health_data(power_data)
            results = self.notify_bypass_servers(health_data, "health")
            
            if results["successful"] > 0:
                self.config["last_health_broadcast"] = datetime.utcnow().isoformat()
                self.save_config(self.config)
                logger.info(f"📡 Health heartbeat sent to {results['successful']} servers")
            else:
                logger.warning(f"❌ Health heartbeat failed for all servers")

def main():
    """Main monitoring loop for testing"""
    notifier = BypassNotifier()
    
    logger.info(f"Starting bypass notifier for unit {notifier.config['unit_id']}")
    
    while True:
        try:
            # Mock power data for testing
            power_data = {
                "battery_percent": 85.0,
                "battery_voltage": 4.1,
                "external_power": True
            }
            
            # Monitor WireGuard and send notifications
            notifier.monitor_wireguard_status(power_data)
            
            # Track battery runtime
            notifier.track_battery_runtime(power_data)
            
            time.sleep(30)  # Check every 30 seconds
            
        except KeyboardInterrupt:
            logger.info("Bypass notifier stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            time.sleep(60)  # Wait longer on errors

if __name__ == "__main__":
    main()