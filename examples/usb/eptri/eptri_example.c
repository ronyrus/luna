/**
 * This file is part of LUNA.
 */

#include <stdbool.h>

#include "resources.h"


/**
 * Struct representing a USB setup request.
 */
union usb_setup_request 
{
	struct
	{
		union {
			struct 
			{
				uint8_t bmRequestType;
				uint8_t bRequest;
			};

			uint16_t wRequestAndType;
		};

    uint16_t wValue;
    uint16_t wIndex;
    uint16_t wLength;
    };

	// Window that allows us to capture raw data into the setup request, easily.
	uint8_t raw_data[8];
};
typedef union usb_setup_request usb_setup_request_t;


//
// Globals
//
usb_setup_request_t last_setup_packet;


//
// Descriptors.
//

//static const uint8_t usb_device_descriptor[] = {
//    0x12, 0x01, 0x00, 0x02, 0x00, 0x00, 0x00, 0x40,
//    0x09, 0x12, 0xf0, 0x5b, 0x01, 0x01, 0x01, 0x02,
//    0x00, 0x01
//};
//
//static const uint8_t usb_config_descriptor[] = {
//    0x09, 0x02, 0x12, 0x00, 0x01, 0x01, 0x01, 0x80,
//    0x32, 0x09, 0x04, 0x00, 0x00, 0x00, 0xfe, 0x00,
//    0x00, 0x02
//};
//        
//static const uint8_t usb_string0_descriptor[] = {
//    0x04, 0x03, 0x09, 0x04,
//};
//
//static const uint8_t usb_string1_descriptor[] = {
//    0x0e, 0x03, 0x46, 0x00, 0x6f, 0x00, 0x6f, 0x00,
//    0x73, 0x00, 0x6e, 0x00, 0x00, 0x00,
//};
//
//static const uint8_t usb_string2_descriptor[] = {
//    0x1a, 0x03, 0x46, 0x00, 0x6f, 0x00, 0x6d, 0x00,
//    0x75, 0x00, 0x20, 0x00, 0x55, 0x00, 0x70, 0x00,
//    0x64, 0x00, 0x61, 0x00, 0x74, 0x00, 0x65, 0x00,
//    0x72, 0x00,
//};
//
//static const uint8_t usb_bos_descriptor[] = {
//    0x05, 0x0f, 0x1d, 0x00, 0x01, 0x18, 0x10, 0x05,
//    0x00, 0x38, 0xb6, 0x08, 0x34, 0xa9, 0x09, 0xa0,
//    0x47, 0x8b, 0xfd, 0xa0, 0x76, 0x88, 0x15, 0xb6,
//    0x65, 0x00, 0x01, 0x02, 0x01,
//};
//
//static const uint8_t usb_ms_compat_id_descriptor[] = {
//    0x28, 0x00, 0x00, 0x00, 0x00, 0x01, 0x04, 0x00,
//    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
//    0x00, 0x01, 0x57, 0x49, 0x4e, 0x55, 0x53, 0x42,
//    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
//    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
//};
//

/**
 * Transmits a single charater over our example UART.
 */
void print_char(char c)
{
	while(!uart_tx_rdy_read());
	uart_tx_data_write(c);
}


/**
 * Transmits a string over our UART.
 */
void uart_puts(char *str)
{
	for (char *c = str; *c; ++c) {
		if (*c == '\n') {
			print_char('\r');
		}

		print_char(*c);
	}
}


/**
 * Prints a hex character over our UART.
 */
void print_nibble(uint8_t nibble)
{
	static const char hexits[] = "0123456789abcdef";
	print_char(hexits[nibble & 0xf]);
}


/**
 * Prints a single byte, in hex, over our UART.
 */
void print_byte(uint8_t byte)
{
	print_nibble(byte >> 4);
	print_nibble(byte & 0xf);
}


/**
 * Reads a setup request from our interface, populating our SETUP request field.
 */
void read_setup_request(void)
{
	for (uint8_t i = 0; i < 8; ++i) {

		// Block until we have setup data to read.
		while(!setup_have_read());

		// Once it's available, read the setup field for our packet.
		uint8_t byte = setup_data_read();
		last_setup_packet.raw_data[i] = byte;
	}
}



int main(void)
{
	uart_puts("eptri demo started!\n");

	while(1) {

		// Read the next SETUP request.
		read_setup_request();

		uart_puts("Got SETUP request ");
		print_byte(last_setup_packet.bRequest);
		uart_puts(" on endpoint ");
		print_byte(setup_epno_read());
		uart_puts(".\n");
	}
}
