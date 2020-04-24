#
# This file is part of LUNA.
#
""" Implementation of a Triple-FIFO endpoint manager (eptri); compatible with ValentyUSB. """

from nmigen             import Elaboratable, Module
from nmigen.lib.fifo    import SyncFIFOBuffered
from nmigen.hdl.xfrm    import ResetInserter


from ..endpoint         import EndpointInterface
from ....soc.peripheral import Peripheral


class SetupFIFOInterface(Peripheral, Elaboratable):
    """ Setup component of our `eptri`-equivalent interface.

    Implements the USB Setup FIFO, which handles SETUP packets on any endpoint.

    This interface is similar to an :class:`OutFIFOInterface`, but always ACKs packets,
    and does not allow for any flow control; as a USB device must always be ready to accept
    control packets. [USB2.0: 8.6.1]

    Attributes
    -----

    interface: EndpointInterface
        Our primary interface to the core USB device hardware.
    """

    def __init__(self):
        super().__init__()

        #
        # Registers
        #

        # FIXME: These should be organized to have the same memory layout as the ValentyUSB
        # eptri interface, for compatibility.

        regs = self.csr_bank()
        self.data = regs.csr(8, "r", desc="""
            A FIFO that returns the bytes from the most recently captured SETUP packet.
            Reading a byte from this register advances the FIFO. The first eight bytes read
            from this conain the core SETUP packet.
        """)

        self.reset = regs.csr(1, "w", desc="""
            Local reset control for the SETUP handler; writing a '1' to this register clears the handler state.
        """)

        self.epno = regs.csr(4, "r", desc="The number of the endpoint associated with the current SETUP packet.")
        self.have = regs.csr(1, "r", desc="`1` iff data is available in the FIFO.")
        self.pend = regs.csr(1, "r", desc="`1` iff an interrupt is pending")

        #
        # I/O port
        #
        self.interface = EndpointInterface()

        #
        # Internals
        #

        # Act as a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus



    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        token = self.interface.tokenizer
        rx    = self.interface.rx

        # Logic condition for getting a new setup packet.
        new_setup = token.new_token & token.is_setup

        #
        # Core FIFO.
        #
        m.submodules.fifo = fifo = ResetInserter(new_setup)(SyncFIFOBuffered(width=8, depth=10))

        m.d.comb += [

            # We'll write to the active FIFO whenever the last received token is a SETUP
            # token, and we have incoming data; and we'll always write the data received
            fifo.w_en         .eq(token.is_setup & rx.valid & rx.next),
            fifo.w_data       .eq(rx.payload),

            # We'll advance the FIFO whenever our CPU reads from the data CSR;
            # and we'll always read our data from the FIFO.
            fifo.r_en         .eq(self.data.r_stb),
            self.data.r_data  .eq(fifo.r_data),

            # Pass the FIFO status on to our CPU.
            self.have.r_data  .eq(fifo.r_rdy)
        ]


        #
        # Status and interrupts.
        #

        with m.If(token.new_token):
            m.d.usb += self.epno.r_data.eq(token.endpoint)


        # TODO: generate interrupts

        return m



class InFIFOInterface(Peripheral, Elaboratable):
    """ IN component of our `eptri`-equivalent interface.

    Implements the FIFO that handles `eptri` IN requests. This FIFO collects USB data, and
    transmits it in response to an IN token. Like all `eptri` interfaces; it can handle only one
    pending packet at a time.


    Attributes
    -----

    interface: EndpointInterface
        Our primary interface to the core USB device hardware.

    """


    def __init__(self, max_packet_size=64):
        """
        Parameters
        ----------
            max_packet_size: int, optional
                Sets the maximum packet size that can be transmitted on this endpoint.
                This should match the value provided in the relevant endpoint descriptor.
        """

        super().__init__()

        self.max_packet_size = max_packet_size

        #
        # Registers
        #

        # FIXME: These should be organized to have the same memory layout as the ValentyUSB
        # eptri interface, for compatibility.

        regs = self.csr_bank()

        self.data = regs.csr(8, "w", desc="""
            Write-only register. Each write enqueues a byte to be transmitted; gradually building
            a single packet to be transmitted. This queue should only ever contain a single packet;
            it is the software's responsibility to handle breaking requests down into packets.
        """)

        self.epno = regs.csr(4, "rw", desc="""
            Contains the endpoint the enqueued packet is to be transmitted on. Writing this register
            marks the relevant packet as ready to transmit; and thus should only be written after a
            full packet has been written into the FIFO. If no data has been placed into the DATA FIFO,
            a zero-length packet is generated.

            Note that any IN requests that do not match the endpoint number are automatically NAK'd.
        """)

        self.reset = regs.csr(1, "w", desc="A write to this register clears the FIFO without transmitting.")

        self.stall = regs.csr(1, "rw", desc="""
            When this register contains '1', any IN tokens targeting `epno` will be responded to with a
            STALL token, rather than DATA or a NAK. To avoid a race, to stall an endpoint, write `stall`
            before updating the `epno` register.

            For EP0, this register will automatically be cleared when a new SETUP token is received.
        """)


        self.idle = regs.csr(1, "r", desc="This value is `1` if no packet is actively being transmitted.")
        self.have = regs.csr(1, "r", desc="This value is `1` if the transmit FIFO is empty.")
        self.pend = regs.csr(1, "r", desc="`1` iff an interrupt is pending")


        #
        # I/O port
        #
        self.interface = EndpointInterface()

        #
        # Internals
        #

        # Act as a Wishbone peripheral.
        self._bridge    = self.bridge(data_width=32, granularity=8, alignment=2)
        self.bus        = self._bridge.bus



    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        token = self.interface.tokenizer
        rx    = self.interface.rx

        return m
