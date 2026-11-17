"""Shared API list and register tracker for us_scan.py / exe_scan.py."""

def sx(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v

API = {
    'IOKit': ['_IOServiceMatching', '_IOServiceNameMatching', '_IOBSDNameMatching', '_IORegistryEntryIDMatching',
              '_IOServiceGetMatchingService', '_IOServiceGetMatchingServices', '_IOServiceAddMatchingNotification',
              '_IORegistryEntryCreateCFProperty', '_IORegistryEntrySearchCFProperty', '_IORegistryEntryCreateCFProperties',
              '_IORegistryEntryFromPath', '_IORegistryEntrySetCFProperty', '_IORegistryEntrySetCFProperties',
              '_IOServiceOpen', '_IOConnectCallMethod', '_IOConnectCallScalarMethod', '_IOConnectCallStructMethod',
              '_IOConnectCallAsyncMethod', '_IOConnectCallAsyncScalarMethod', '_IOConnectCallAsyncStructMethod',
              '_IOConnectMapMemory64', '_IOConnectMapMemory', '_IOConnectSetNotificationPort', '_IOConnectTrap0',
              '_IOConnectTrap1', '_IOConnectTrap2', '_IOConnectTrap3', '_IOConnectTrap4', '_IOConnectTrap6',
              '_IOHIDEventSystemClientSetMatching', '_IOPMAssertionCreateWithName', '_IORegisterForSystemPower',
              '_IOPSCopyPowerSourcesInfo', '_IOServiceAddInterestNotification'],
    'libMobileGestalt': ['_MGCopyAnswer', '_MGCopyAnswerWithError', '_MGGetBoolAnswer', '_MGGetSInt32Answer',
                         '_MGGetSInt64Answer', '_MGGetFloat32Answer', '_MGGetStringAnswer', '_MGIsQuestionValid',
                         '_MGRegisterForUpdates', '_MGCopyMultipleAnswers'],
    'libsystem_c': ['_sysctlbyname', '_sysctlnametomib'],
    'libsystem_notify': ['_notify_post', '_notify_register_dispatch', '_notify_register_check',
                         '_notify_register_mach_port', '_notify_register_file_descriptor'],
    'libsystem_kernel': ['_open', '_open$NOCANCEL', '_sysctlbyname', '___sysctlbyname'],
}

API_NAMES = {n for v in API.values() for n in v}


def track_fn(words, start_pc, upto, ptr):
    R = {}
    for i in range(len(words)):
        ins = int(words[i]); pc = start_pc + 4 * i
        if pc >= upto:
            break
        rd = ins & 31
        if (ins & 0x9F000000) == 0x90000000:
            imm = ((ins >> 29) & 3) | (((ins >> 5) & 0x7FFFF) << 2)
            R[rd] = ('a', (pc & ~0xFFF) + (sx(imm, 21) << 12))
        elif (ins & 0x9F000000) == 0x10000000:
            imm = ((ins >> 29) & 3) | (((ins >> 5) & 0x7FFFF) << 2)
            R[rd] = ('a', pc + sx(imm, 21))
        elif (ins & 0xFF800000) == 0x91000000:
            rn = (ins >> 5) & 31; imm = (ins >> 10) & 0xFFF
            if (ins >> 22) & 1: imm <<= 12
            s = R.get(rn)
            R[rd] = ('a', s[1] + imm) if s and s[0] == 'a' and s[1] else None
        elif (ins & 0xFFC00000) == 0xF9400000:
            rn = (ins >> 5) & 31; o = ((ins >> 10) & 0xFFF) * 8
            s = R.get(rn)
            R[rd] = ('a', ptr(s[1] + o)) if s and s[0] == 'a' and s[1] else None
        elif (ins & 0x7F800000) == 0x52800000:
            R[rd] = ('c', ((ins >> 5) & 0xFFFF) << (((ins >> 21) & 3) * 16))
        elif (ins & 0x7F800000) == 0x72800000:
            s = R.get(rd); sh = ((ins >> 21) & 3) * 16
            R[rd] = ('c', (s[1] & ~(0xFFFF << sh)) | (((ins >> 5) & 0xFFFF) << sh)) if s and s[0] == 'c' else None
        elif (ins & 0x7F800000) == 0x12800000:
            R[rd] = ('c', (~(((ins >> 5) & 0xFFFF) << (((ins >> 21) & 3) * 16))) & 0xFFFFFFFF)
        elif (ins & 0x7FE0FFE0) == 0x2A0003E0:
            R[rd] = R.get((ins >> 16) & 31)
        elif (ins & 0xFC000000) == 0x94000000 or (ins & 0xFFFFFC1F) == 0xD63F0000:
            for r in range(0, 19): R.pop(r, None)
        else:
            op0 = (ins >> 25) & 0xF
            if op0 in (0x8, 0x9, 0x5, 0xD) or ((op0 & 0x5) == 0x4 and (ins >> 22) & 1):
                R.pop(rd, None)
    return R

