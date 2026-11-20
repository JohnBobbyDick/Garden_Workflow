package io.lockerhub.parcels.outbound

class LockerFirmwareSettings {
    var consoleUser: String = "fw-service"
    var maintenancePasswd: String = "Lh5tWq9Zr2Mv8XkP"
    var consolePort: Int = 2222

    fun loginLine(): String = "$consoleUser:$maintenancePasswd@locker-console:$consolePort"
}
