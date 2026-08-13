package com.itamar.smsbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NetTest {

    @Test
    fun `a tunnel interface on a CGNAT address is Tailscale`() {
        assertEquals(Net.Kind.TAILSCALE, Net.classify("tun0", "100.101.102.103"))
        assertEquals(Net.Kind.TAILSCALE, Net.classify("ts0", "100.64.0.1"))
    }

    @Test
    fun `a carrier CGNAT address is not mistaken for Tailscale`() {
        // Mobile networks hand out 100.64/10 too; only a tunnel interface counts.
        assertEquals(Net.Kind.OTHER, Net.classify("rmnet_data0", "100.71.4.9"))
    }

    @Test
    fun `private addresses on ordinary interfaces are LAN`() {
        assertEquals(Net.Kind.LAN, Net.classify("wlan0", "192.168.1.23"))
        assertEquals(Net.Kind.LAN, Net.classify("wlan0", "10.0.0.5"))
        assertEquals(Net.Kind.LAN, Net.classify("eth0", "172.20.1.1"))
    }

    @Test
    fun `a private address on a cellular interface is not offered as LAN`() {
        // Reachable from nowhere the iPhone will ever be, so it must not win the QR code.
        assertEquals(Net.Kind.OTHER, Net.classify("rmnet_data2", "10.51.2.3"))
        assertEquals(Net.Kind.OTHER, Net.classify("ccmni0", "10.51.2.3"))
    }

    @Test
    fun `public addresses are not treated as locally reachable`() {
        assertEquals(Net.Kind.OTHER, Net.classify("wlan0", "8.8.8.8"))
        assertEquals(Net.Kind.OTHER, Net.classify("wlan0", "172.32.0.1"))
        assertEquals(Net.Kind.OTHER, Net.classify("wlan0", "192.169.1.1"))
    }

    @Test
    fun `CGNAT range boundaries`() {
        assertTrue(Net.isCgnat("100.64.0.0"))
        assertTrue(Net.isCgnat("100.127.255.255"))
        assertFalse(Net.isCgnat("100.63.255.255"))
        assertFalse(Net.isCgnat("100.128.0.0"))
        assertFalse(Net.isCgnat("101.64.0.1"))
    }

    @Test
    fun `private range boundaries`() {
        assertTrue(Net.isPrivate("172.16.0.1"))
        assertTrue(Net.isPrivate("172.31.255.254"))
        assertFalse(Net.isPrivate("172.15.0.1"))
        assertFalse(Net.isPrivate("172.32.0.1"))
        assertFalse(Net.isPrivate("192.167.1.1"))
    }

    @Test
    fun `malformed addresses never classify as reachable`() {
        assertFalse(Net.isCgnat("not-an-ip"))
        assertFalse(Net.isPrivate("192.168"))
        assertFalse(Net.isPrivate(""))
        assertEquals(Net.Kind.OTHER, Net.classify("wlan0", "garbage"))
    }
}
