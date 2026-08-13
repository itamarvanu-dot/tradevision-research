package com.itamar.smsbridge

import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * Finds the addresses the iPhone can actually reach this phone on.
 *
 * The important distinction is Tailscale versus everything else: a Tailscale address stays
 * the same as the phone moves between Wi-Fi and cellular and is reachable from anywhere,
 * while a Wi-Fi address only works while both phones sit on the same network.
 */
object Net {

    enum class Kind {
        /** Reachable from anywhere, survives network changes. */
        TAILSCALE,

        /** Reachable only from the same local network. */
        LAN,

        /** Mobile data and anything else — almost never reachable from another device. */
        OTHER,
    }

    data class Address(val ip: String, val kind: Kind, val interfaceName: String)

    /** Best first: Tailscale, then Wi-Fi, then the rest. */
    fun addresses(): List<Address> = try {
        NetworkInterface.getNetworkInterfaces().asSequence()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { nif ->
                nif.inetAddresses.asSequence()
                    .filterIsInstance<Inet4Address>()
                    .filterNot { it.isLoopbackAddress || it.isLinkLocalAddress }
                    .mapNotNull { it.hostAddress }
                    .map { ip -> Address(ip, classify(nif.name, ip), nif.name) }
            }
            .sortedBy { rank(it.kind) }
            .toList()
    } catch (_: Exception) {
        emptyList()
    }

    /** The address to put in the QR code, or null when the phone is on no usable network. */
    fun preferred(): Address? = addresses().firstOrNull { it.kind != Kind.OTHER }

    private fun rank(kind: Kind): Int = when (kind) {
        Kind.TAILSCALE -> 0
        Kind.LAN -> 1
        Kind.OTHER -> 2
    }

    internal fun classify(interfaceName: String, ip: String): Kind = when {
        // Carriers hand out 100.64/10 addresses too, so the interface has to be a tunnel
        // before a CGNAT address counts as Tailscale.
        isTunnel(interfaceName) && isCgnat(ip) -> Kind.TAILSCALE
        isCellular(interfaceName) -> Kind.OTHER
        isPrivate(ip) -> Kind.LAN
        else -> Kind.OTHER
    }

    internal fun isTunnel(name: String): Boolean =
        name.startsWith("tun") || name.startsWith("ts") ||
            name.startsWith("wg") || name.startsWith("utun")

    internal fun isCellular(name: String): Boolean =
        name.startsWith("rmnet") || name.startsWith("ccmni") ||
            name.startsWith("pdp") || name.startsWith("clat")

    /** The 100.64.0.0/10 shared-address space that Tailscale allocates from. */
    internal fun isCgnat(ip: String): Boolean {
        val parts = ip.split('.')
        if (parts.size != 4) return false
        val first = parts[0].toIntOrNull() ?: return false
        val second = parts[1].toIntOrNull() ?: return false
        return first == 100 && second in 64..127
    }

    internal fun isPrivate(ip: String): Boolean {
        val parts = ip.split('.')
        if (parts.size != 4) return false
        val first = parts[0].toIntOrNull() ?: return false
        val second = parts[1].toIntOrNull() ?: return false
        return when (first) {
            10 -> true
            192 -> second == 168
            172 -> second in 16..31
            else -> false
        }
    }
}
