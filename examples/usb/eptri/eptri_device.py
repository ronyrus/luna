#!/usr/bin/env python3
#
# This file is part of LUNA.
#

from nmigen                                  import Elaboratable, Module, Cat
from nmigen.hdl.rec                          import Record

from luna                                    import top_level_cli
from luna.gateware.soc                       import SimpleSoC
from luna.gateware.architecture.car          import LunaECP5DomainGenerator

from luna.gateware.usb.usb2.device           import USBDevice
from luna.gateware.usb.usb2.interfaces.eptri import SetupFIFOInterface, InFIFOInterface


CLOCK_FREQUENCIES_MHZ = {
    'sync': 60
}


class EptriDeviceExample(Elaboratable):
    """ Example of an Eptri-equivalent USB device built with LUNA. """

    def __init__(self):

        # Create a stand-in for our UART.
        self.uart_pins = Record([
            ('rx', [('i', 1)]),
            ('tx', [('o', 1)])
        ])

        # Create our SoC...
        self.soc = soc = SimpleSoC()
        soc.add_bios_and_peripherals(uart_pins=self.uart_pins)

        # ... add some bulk RAM ...
        soc.add_ram(0x4000)

        # ... and add our eptri peripherals.
        self.setup = SetupFIFOInterface()
        soc.add_peripheral(self.setup, as_submodule=False)

        self.in_ep = InFIFOInterface()
        soc.add_peripheral(self.in_ep, as_submodule=False)



    def elaborate(self, platform):
        m = Module()
        m.submodules.soc = self.soc

        # Generate our domain clocks/resets.
        m.submodules.car = LunaECP5DomainGenerator(clock_frequencies=CLOCK_FREQUENCIES_MHZ)

        # Connect up our UART.
        uart_io = platform.request("uart", 0)
        m.d.comb += [
            uart_io.tx         .eq(self.uart_pins.tx),
            self.uart_pins.rx  .eq(uart_io.rx)
        ]

        # Create our USB device.
        ulpi = platform.request("target_phy")
        m.submodules.usb = usb = USBDevice(bus=ulpi)

        # TODO: move this to an SoC interface?
        m.d.comb += [
            usb.connect.eq(1)
        ]

        # Add our eptri endpoint handlers.
        usb.add_endpoint(self.setup)
        usb.add_endpoint(self.in_ep)
        return m


if __name__ == "__main__":
    design = EptriDeviceExample()
    top_level_cli(design, cli_soc=design.soc)
