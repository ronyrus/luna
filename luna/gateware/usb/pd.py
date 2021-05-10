from math import ceil, log2

from nmigen import Elaboratable, Module, Signal, Cat, Const, ClockSignal
from nmigen.hdl.ast import Rose, Fell
from nmigen.hdl.rec import DIR_FANIN, DIR_FANOUT
from luna.gateware.utils.cdc import synchronize
from luna.gateware.test import LunaGatewareTestCase, sync_test_case

def ns2clk(ns, clk_freq):
    clk_cycle_time_sec = 1/clk_freq
    required_time_sec = ns/1e9
    assert required_time_sec > clk_cycle_time_sec, "Required time is less than 1 clock."
    return ceil(required_time_sec / clk_cycle_time_sec)


class BMCTimer(Elaboratable):

    def us2clk(self, us):
        return ns2clk(us * 1000, self._clock_frequency)

    def ms2clk(self, ms):
        return ns2clk(ms * 1000 * 1000, self._clock_frequency)


    def __init__(self, domain_clock_frequency):
        self._clock_frequency = domain_clock_frequency

        # USB-PD R3 5.8.4 BMC Common specifications
        # Nominal bit rate (fBitRate) is 300 Kbps
        # Min bit rate 270 Kbps, Max bit rate is 330 Kbps

        # Unit Interval (UI)
        self._unit_interval_min = self.us2clk(3.03)
        self._unit_interval_nom = self.us2clk(3.33)
        self._unit_interval_max = self.us2clk(3.70)

        # Half Unit Interval
        self._half_unit_interval_min = self.us2clk(3.03/2)
        self._half_unit_interval_nom = self.us2clk(3.33/2)
        self._half_unit_interval_max = self.us2clk(3.70/2)

        # First bit in preamble is 0 and it's special (see Figure 5-10 in R3 USB-PD Spec).
        # It can deviate from UI by +/- tStartDrive, which is 1us
        self._tStartDrive = self.us2clk(1)
        self._first_bit_interval_min = self._unit_interval_min - self._tStartDrive
        self._first_bit_interval_max = self._unit_interval_max + self._tStartDrive

        self._ticks_for_10_usec = self.us2clk(10)

        # maximum interval that we need to count to in clocks
        # XXX: if you add new intervals, don't forget to check if this needs updating!
        self._counter_max = self._ticks_for_10_usec

        self.counter = Signal(range(0, self._counter_max + 1))

        # assert to reset the timer
        self.start = Signal()

        # external signals for points in time
        self.first_bit_min = Signal()
        self.first_bit_max = Signal()
        self.first_bit_valid = Signal()

        self.unit_interval_min = Signal()
        self.unit_interval_max = Signal()
        self.unit_interval_nom = Signal()
        self.unit_interval_valid = Signal()

        self.half_unit_interval_min = Signal()
        self.half_unit_interval_max = Signal()
        self.half_unit_interval_nom = Signal()
        self.half_unit_interval_valid = Signal()

        self.interval_10_usec = Signal()


    def elaborate(self, platform):
        m = Module()

        # reset the counter and all interval markers
        with m.If(self.start):
            m.d.sync += [
                self.counter.eq(0),
                self.first_bit_min.eq(0),
                self.first_bit_max.eq(0),
                self.unit_interval_min.eq(0),
                self.unit_interval_max.eq(0),
                self.half_unit_interval_min.eq(0),
                self.half_unit_interval_max.eq(0),
            ]
        # counter go BRRRR
        with m.Else():
            m.d.sync += self.counter.eq(self.counter + 1)

        # we are valid if we passed min and didn't get to max yet
        m.d.comb += [
            self.first_bit_valid.eq(self.first_bit_min & ~self.first_bit_max),
            self.unit_interval_valid.eq(self.unit_interval_min & ~self.unit_interval_max),
            self.half_unit_interval_valid.eq(self.half_unit_interval_min & ~self.half_unit_interval_max),
        ]

        # XXX: I wanted to use "Elif", but what if we'll have two identical intervals someday?
        with m.If(self.counter == self._first_bit_interval_min):
            m.d.sync += self.first_bit_min.eq(1)
        with m.If(self.counter == self._first_bit_interval_max):
            m.d.sync += self.first_bit_max.eq(1)
        with m.If(self.counter == self._unit_interval_min):
            m.d.sync += self.unit_interval_min.eq(1)
        with m.If(self.counter == self._unit_interval_max):
            m.d.sync += self.unit_interval_max.eq(1)
        with m.If(self.counter == self._half_unit_interval_min):
            m.d.sync += self.half_unit_interval_min.eq(1)
        with m.If(self.counter == self._half_unit_interval_max):
            m.d.sync += self.half_unit_interval_max.eq(1)

        m.d.comb += [
            self.half_unit_interval_nom.eq(self.counter == self._half_unit_interval_nom),
            self.unit_interval_nom.eq(self.counter == self._unit_interval_nom),
            self.interval_10_usec.eq(self.counter == self._ticks_for_10_usec),
        ]

        return m


class BMCTimerTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = 100e6 # easier to calculate time
    FRAGMENT_UNDER_TEST = BMCTimer
    FRAGMENT_ARGUMENTS = {"domain_clock_frequency": SYNC_CLOCK_FREQUENCY}

    def get_first_bit_flags(self):
        min = yield self.dut.first_bit_min
        max = yield self.dut.first_bit_max
        valid = yield self.dut.first_bit_valid
        return (min, max, valid)

    def get_half_unit_interval_flags(self):
        min = yield self.dut.half_unit_interval_min
        max = yield self.dut.half_unit_interval_max
        valid = yield self.dut.half_unit_interval_valid
        return (min, max, valid)

    def get_unit_interval_flags(self):
        min = yield self.dut.unit_interval_min
        max = yield self.dut.unit_interval_max
        valid = yield self.dut.unit_interval_valid
        return (min, max, valid)


    @sync_test_case
    def test_timers(self):
        yield from self.advance_cycles(10) # advance 100 ns

        # we only advanced a little, all flags supposed to be cleared
        self.assertEqual((yield from self.get_half_unit_interval_flags()), (0,0,0))
        
        # 1.515 us < [half unit interval] < 1.85 us
        # advance 1.55 us
        yield from self.wait(0.00000155)

        # we passed half interval min and didn't reach max, so we are valid
        self.assertEqual((yield from self.get_half_unit_interval_flags()), (1,0,1))

        # advance 0.5 us
        yield from self.wait(0.0000005)

        # now we passed half interval max, so, not valid, but min and max set
        self.assertEqual((yield from self.get_half_unit_interval_flags()), (1,1,0))

        # test that flags are cleared on reset pulse
        yield from self.pulse(self.dut.start)
        self.assertEqual((yield from self.get_half_unit_interval_flags()), (0,0,0))

        # test that counter is not moving if reset signal asserted
        yield self.dut.start.eq(1)
        yield
        yield from self.wait(0.00000155)
        self.assertEqual((yield from self.get_half_unit_interval_flags()), (0,0,0))

        # test that if counter overflows, flags stay the same
        # reset
        yield from self.pulse(self.dut.start)

        # wait for half unit interval min and max to be set
        yield from self.wait(0.00000255)
        self.assertEqual((yield from self.get_half_unit_interval_flags()), (1,1,0))

        # advance past counter max value and check again
        counter_max = 1 << self.dut.counter.shape().width
        yield from self.advance_cycles(counter_max)
        self.assertEqual((yield from self.get_half_unit_interval_flags()), (1,1,0))

        # XXX: should we test all the intervals? probably need to automate it...



class BMCDecoder(Elaboratable):

    def __init__(self, domain_clock_frequency):
        self._clock_frequency = domain_clock_frequency

        self.cc = Signal()
        self.data = Signal()
        self.valid = Signal()
        # self.rx_active = Signal() # XXX: probably a good idea, so upper layer would know when we receive something

    def elaborate(self, platform):
        m = Module()

        m.submodules.timer = timer = BMCTimer(self._clock_frequency)

        # Synchronize CC line to our clock domain
        sync_cc = synchronize(m, self.cc, o_domain="sync")

        # Edge detection.
        # The bits are encoded as time between transitions. Hence, any edge is considered an event.
        edge = Signal()
        rising_edge  = Rose(sync_cc, domain="sync")
        falling_edge = Fell(sync_cc, domain="sync")
        m.d.comb += edge.eq(rising_edge | falling_edge)

        next_bit_is_one = Signal()

        with m.FSM(domain="sync") as fsm:

            # Line is IDLE.
            with m.State("IDLE"):
                # USB-PD Chapter 5.6
                # A packet always starts with a preamble.
                # A preamble consists of 64 alternating 1-s and 0-s, starting with 0 and ending with 1.
                # The first bit is always zero and the transmission starts with driving the 'low' level.
                # The spec requires the receiver to tolarate the loss of the first edge (USB-PD R3 5.8.1).

                # Detected the first edge.
                with m.If(falling_edge):
                    m.d.comb += timer.start.eq(1)
                    m.next = "FRAME_STARTED"

                # Lost the first edge.
                with m.If(rising_edge):

                    # Because we missed the first edge, we don't know how much time has passed.
                    # So we can't check that we are within 1UI +/- tStartDrive.
                    # XXX: Is there a way to know?
                    m.d.comb += [
                        self.data.eq(0),
                        self.valid.eq(1),
                        timer.start.eq(1),
                    ]
                    m.next = "RECV_NEXT_BIT"

            # Detected the first edge of the frame (from IDLE line to low).
            # This is the start of the preamble.
            # The transmitter May vary the start of the Preamble by tStartDrive (USB-PD R3 5.8.1)
            with m.State("FRAME_STARTED"):
                # timed out
                # XXX: should we signal error or something?
                with m.If(timer.first_bit_max):
                    m.next = "IDLE"

                # within bound, it's a solid 0
                with m.Elif(rising_edge & timer.first_bit_min):
                    m.d.comb += [
                        self.data.eq(0),
                        self.valid.eq(1),
                        timer.start.eq(1),
                    ]
                    m.next = "RECV_NEXT_BIT"
                    

            with m.State("RECV_NEXT_BIT"):

                # no edges, we are probably done receiving
                with m.If(timer.unit_interval_max):
                    m.next = "IDLE"
                    
                with m.Elif(edge):
                    # transition in the middle of UI means 1
                    with m.If(timer.half_unit_interval_valid):
                        m.d.sync += next_bit_is_one.eq(1)
                    
                    # transition on UI boundary, this bit is ready :)
                    with m.Elif(timer.unit_interval_valid):
                        m.d.comb += [
                            # make the result visible
                            self.data.eq(next_bit_is_one),
                            self.valid.eq(1),

                            # restart the timer for the next bit
                            timer.start.eq(1),
                        ]
                        # reset 1/0 toggle on the next clock
                        m.d.sync += next_bit_is_one.eq(0)

        return m



class BMCDecoderTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = 100e6 # easier to calculate time
    FRAGMENT_UNDER_TEST = BMCDecoder
    FRAGMENT_ARGUMENTS = {"domain_clock_frequency": SYNC_CLOCK_FREQUENCY}

    # wait more than max UI without changing CC, makes us go to IDLE
    def wait_for_idle(self):
        yield from self.wait(0.000_010)

    def flip_cc(self):
        yield self.dut.cc.eq(int(not (yield self.dut.cc)))

    def transmit_zero(self):
        """
        This function assumes that the CC was already flipped once.
        """
        # wait bit time
        yield from self.wait(0.000_003_3)
        # flip the bit and let it register
        yield from self.flip_cc()
        yield from self.advance_cycles(3)


    def transmit_one(self):
        """
        This function assumes that the CC was already flipped once.
        """
        # wait half bit time
        yield from self.wait(0.000_001_65)
        # flip the bit
        yield from self.flip_cc()
        # wait half bit time
        yield from self.wait(0.000_001_65)
        # flip the bit and let it register
        yield from self.flip_cc()
        yield from self.advance_cycles(3)
        

    @sync_test_case
    def test_losing_first_edge(self):
        """
        This test simulates the lack of the first falling edge of the preamble.
        It then transmits a valid 1.
        Expected output would be 0 and then 1.
        """
        # CC is low
        yield self.dut.cc.eq(0)
        # nothing on TV
        yield from self.wait_for_idle()

        # raising edge from IDLE, meaning we lost the first falling edge
        yield self.dut.cc.eq(1)
        # cycle-1: CC set, cycle-2: Sync CC set, cycle-3: edge detected 
        yield from self.advance_cycles(3)

        # should output valid 0
        self.assertEqual((yield self.dut.data), 0)
        self.assertEqual((yield self.dut.valid), 1)

        yield from self.transmit_one()

        # should output valid 1
        self.assertEqual((yield self.dut.data), 1)
        self.assertEqual((yield self.dut.valid), 1)


    @sync_test_case
    def test_receiving_preamble(self):
        """
        Well, receiving a preamble, you know ...
        """
        # we start from IDLE
        yield self.dut.cc.eq(1)
        yield from self.wait_for_idle()

        # preamble start by driving low
        yield self.dut.cc.eq(0)

        for i in range(64):
            is_even = i % 2 == 0

            # we alternate 0s and 1s, starting from 0
            if is_even:
                yield from self.transmit_zero()
                self.assertEqual((yield self.dut.data), 0)
            else:
                yield from self.transmit_one()
                self.assertEqual((yield self.dut.data), 1)

            self.assertEqual((yield self.dut.valid), 1)


class BMCEncoder(Elaboratable):

    def __init__(self, domain_clock_frequency):
        self._clock_frequency = domain_clock_frequency


        self.cc_out = Signal() # O: the CC line data
        self.cc_oe = Signal() # O: the CC line output enable
      
        self.start = Signal() # I: start transmiting
        self.data = Signal() # I: data to transmit
        self.next = Signal() # O: done sending bit
        self.last = Signal() # I: this is the last bit

    def elaborate(self, platform):
        m = Module()

        m.submodules.timer = timer = BMCTimer(self._clock_frequency)

        with m.FSM(domain="sync") as fsm:

            # we drive CC only when not IDLE
            m.d.comb += self.cc_oe.eq(~fsm.ongoing("IDLE"))

            # Just chilling ...
            with m.State("IDLE"):
                # reset the timer
                m.d.comb += timer.start.eq(1)

                with m.If(self.start):
                    # Frame starts with preamble.
                    # Preamble starts by driving low.
                    m.d.sync += self.cc_out.eq(0)
                    m.next = 'SEND_BIT'


            # here we send the data bits
            with m.State("SEND_BIT"):

                # every unit interval
                with m.If(timer.unit_interval_nom):
                    # flip CC
                    m.d.sync += self.cc_out.eq(~self.cc_out)
                    # signal that we are done with this bit
                    m.d.comb += self.next.eq(1)
                    # reset the timer for the next bit
                    m.d.comb += timer.start.eq(1)

                    # last bit has special termination
                    with m.If(self.last):
                        m.next = "LAST_BIT"

                # half interval has passed and we need to send 1 --> flip CC
                with m.If(timer.half_unit_interval_nom & self.data):
                    m.d.sync += self.cc_out.eq(~self.cc_out)


            # Last bit has special termination (USB-PD R3 5.8.1, figures 5-11 to 5.14).
            with m.State("LAST_BIT"):
                # Trailing edge of the final bit was produced by the previous state.
                # If CC is 0 - we wait at least tHoldLowBMC
                # If CC is 1 - we wait 1 UI, set CC to 0, then wait at least tHoldLowBMC
                # 1 UI is 3.33 usec, tHoldLowBMC is 1 usec, if we transition to IDLE after 10 usec we cover both cases.
                # The time we hold low should be less than tEndDriveBMC (23 usec) from the last edge of the LAST BIT,
                # 10 usec is less than that, so we are good.

                # 1 UI has passed, if CC is high, we finished waiting 1 UI and set it low
                with m.If(timer.unit_interval_nom & self.cc_out):
                    m.d.sync += self.cc_out.eq(0)

                with m.Elif(timer.interval_10_usec):
                    m.next = "IDLE"

        return m


class BMCEncoderTest(LunaGatewareTestCase):
    SYNC_CLOCK_FREQUENCY = 100e6 # easier to calculate time
    FRAGMENT_UNDER_TEST = BMCEncoder
    FRAGMENT_ARGUMENTS = {"domain_clock_frequency": SYNC_CLOCK_FREQUENCY}


    def us_to_ticks(self, us):
        return ns2clk(us * 1000, self.SYNC_CLOCK_FREQUENCY)


    def is_valid_unit_interval(self, ticks):
        return self.us_to_ticks(3.03) <= ticks <= self.us_to_ticks(3.70)

    def is_valid_half_unit_interval(self, ticks):
        return self.us_to_ticks(3.03/2) <= ticks <= self.us_to_ticks(3.70/2)

    def is_valid_termination_drive(self, ticks):
        """
        We supposed to drive CC low at least tHoldLowBMC (1 us) from the last edge.
        And not more than 23 usec from the last edge of the LAST BIT.
        Because we measure only the time we stay low in the end,
        We use 19.3 (23 - 3.7) as a conservative lower bound that satisfies all the cases.
        """
        return self.us_to_ticks(1) <= ticks <= self.us_to_ticks(19.3)


    def count_ticks(self, level_wanted, validate_next_strobe=False):
        ticks = 0
        # count the ticks
        while (yield self.dut.cc_out) == level_wanted and (yield self.dut.cc_oe):
            ticks += 1
            next = (yield self.dut.next)
            yield

        if validate_next_strobe:
            self.assertEqual(next, 1)

        return ticks


    def validate_zero(self, polarity, validate_next_strobe=True):
        """
        Make sure that CC encodes a BMC zero.
        Polarity parameter is the high/low as integer (1/0).
        We assume that the first flip already happened.
        """
        ticks = yield from self.count_ticks(polarity, validate_next_strobe)
        self.assertTrue(self.is_valid_unit_interval(ticks), "Wrong timing in encoding 0.")


    def validate_one(self, polarity, validate_next_strobe=True):
        """
        Make sure that CC encodes a BMC one.
        Polarity parameter is the high/low as integer (1/0).
        We assume that the first flip already happened.
        """
        ticks_1 = yield from self.count_ticks(polarity)
        self.assertTrue(self.is_valid_half_unit_interval(ticks_1), "Wrong timing in encoding 1, first part.")

        ticks_2 = yield from self.count_ticks(int(not polarity), validate_next_strobe)
        self.assertTrue(self.is_valid_half_unit_interval(ticks_2), "Wrong timing in encoding 1, second part.")

        self.assertTrue(self.is_valid_unit_interval(ticks_1 + ticks_2), "Wrong timing in encoding 1, overall time.")


    @sync_test_case
    def test_basics(self):
        """
        Here we test sending a single 0 and a singe 1.
        We also validate that we start driving by asserting CC low.
        """
        # encoder should not drive the line by default
        self.assertEqual((yield self.dut.cc_oe), 0)
        
        # we set cc line to high (as in idle line)
        yield self.dut.cc_out.eq(1)
        
        # trigger transmittion of a single 0
        yield self.dut.data.eq(0)
        yield from self.pulse(self.dut.start, step_after=False)
        yield self.dut.last.eq(1)
        yield from self.advance_cycles(2)
        
        # check that new frame starts by taking CC to low
        self.assertEqual((yield self.dut.cc_out), 0)
        self.assertEqual((yield self.dut.cc_oe), 1)

        # validate it's timing
        yield from self.validate_zero(0)

        # let it finish the last bit termination
        yield from self.wait(0.000_015)

        # transmit a single 1 and validate timing 

        # we set cc line to high (as in idle line)
        yield self.dut.cc_out.eq(1)

        yield self.dut.data.eq(1)
        yield from self.pulse(self.dut.start, step_after=False)
        yield self.dut.last.eq(1)
        yield from self.advance_cycles(2)
        yield from self.validate_one(0)

        # let it finish the last bit termination
        yield from self.wait(0.000_015)


    @sync_test_case
    def test_termination_from_high(self):
        """
        Here we test terminating the frame when the final transition was low -> high.
        """
        # we set cc line to high (as in idle line)
        yield self.dut.cc_out.eq(1)

        # transmit 0 (we start from low, so it ends up on high)
        yield self.dut.data.eq(0)
        yield from self.pulse(self.dut.start, step_after=False)
        yield from self.advance_cycles(2)
        yield from self.validate_zero(0)

        # now transmit 1 (we start from high, but because it's 1 we end up on high again)
        yield self.dut.data.eq(1)
        yield self.dut.last.eq(1)
        yield from self.pulse(self.dut.start, step_after=False)
        yield from self.advance_cycles(2)
        yield from self.validate_one(1)

        # when terminating from high, we stay high for 1 UI
        yield from self.validate_zero(1, validate_next_strobe=False)

        # then CC should go low
        ticks = yield from self.count_ticks(0)
        self.assertTrue(self.is_valid_termination_drive(ticks), "Last bit termination timing error.")

        # we are done driving
        self.assertEqual((yield self.dut.cc_oe), 0)

        # wait 1 usec, just for giggles
        yield from self.wait(0.000_001)


    @sync_test_case
    def test_termination_from_low(self):
        """
        Here we test terminating the frame when the final transition was high -> low.
        """
        # we set cc line to high (as in idle line)
        yield self.dut.cc_out.eq(1)

        # transmit 0 (we start from low, so it ends up on high)
        yield self.dut.data.eq(0)
        yield from self.pulse(self.dut.start, step_after=False)
        yield from self.advance_cycles(2)
        yield from self.validate_zero(0)

        # transmit another 0 (we start from high, so it ends up on low)
        yield self.dut.data.eq(0)
        yield self.dut.last.eq(1)
        yield from self.pulse(self.dut.start, step_after=False)
        yield from self.advance_cycles(2)
        yield from self.validate_zero(1)

        # we continue to drive CC low
        ticks = yield from self.count_ticks(0)
        self.assertTrue(self.is_valid_termination_drive(ticks), "Last bit termination timing error.")

        # we are done driving
        self.assertEqual((yield self.dut.cc_oe), 0)

        # wait 1 usec, just for giggles
        yield from self.wait(0.000_001)
