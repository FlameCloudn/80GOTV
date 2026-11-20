"""Fixed tournament formats used by the bracket editor."""

FORMAT_SPECS = {
    "4se": {
        "name": "4 队单败淘汰",
        "type": "single_elim",
        "total_teams": 4,
        "sections": [
            (
                "淘汰赛",
                [
                    (
                        "半决赛",
                        [
                            ("SF_M1", "半决赛 1", ("seed", 1), ("seed", 4)),
                            ("SF_M2", "半决赛 2", ("seed", 2), ("seed", 3)),
                        ],
                    ),
                    (
                        "决赛",
                        [
                            ("F_M1", "决赛", ("winner", "SF_M1"), ("winner", "SF_M2")),
                        ],
                    ),
                ],
            ),
        ],
    },
    "8se": {
        "name": "8 队单败淘汰",
        "type": "single_elim",
        "total_teams": 8,
        "sections": [
            (
                "淘汰赛",
                [
                    (
                        "四分之一决赛",
                        [
                            ("QF_M1", "四分之一决赛 1", ("seed", 1), ("seed", 8)),
                            ("QF_M2", "四分之一决赛 2", ("seed", 4), ("seed", 5)),
                            ("QF_M3", "四分之一决赛 3", ("seed", 2), ("seed", 7)),
                            ("QF_M4", "四分之一决赛 4", ("seed", 3), ("seed", 6)),
                        ],
                    ),
                    (
                        "半决赛",
                        [
                            ("SF_M1", "半决赛 1", ("winner", "QF_M1"), ("winner", "QF_M2")),
                            ("SF_M2", "半决赛 2", ("winner", "QF_M3"), ("winner", "QF_M4")),
                        ],
                    ),
                    (
                        "决赛",
                        [
                            ("F_M1", "决赛", ("winner", "SF_M1"), ("winner", "SF_M2")),
                        ],
                    ),
                ],
            ),
        ],
    },
    "4de": {
        "name": "4 队双败淘汰",
        "type": "double_elim",
        "total_teams": 4,
        "sections": [
            (
                "胜者组",
                [
                    (
                        "UB 第一轮",
                        [
                            ("UB_R1_M1", "胜者组第一轮 1", ("seed", 1), ("seed", 4)),
                            ("UB_R1_M2", "胜者组第一轮 2", ("seed", 2), ("seed", 3)),
                        ],
                    ),
                    (
                        "UB 第二轮",
                        [
                            (
                                "UB_R2_M1",
                                "胜者组决赛",
                                ("winner", "UB_R1_M1"),
                                ("winner", "UB_R1_M2"),
                            ),
                        ],
                    ),
                ],
            ),
            (
                "败者组",
                [
                    (
                        "LB 第一轮",
                        [
                            (
                                "LB_R1_M1",
                                "败者组第一轮",
                                ("loser", "UB_R1_M1"),
                                ("loser", "UB_R1_M2"),
                            ),
                        ],
                    ),
                    (
                        "败者组决赛",
                        [
                            (
                                "LB_R2_M1",
                                "败者组决赛",
                                ("winner", "LB_R1_M1"),
                                ("loser", "UB_R2_M1"),
                            ),
                        ],
                    ),
                ],
            ),
            (
                "总决赛",
                [
                    (
                        "总决赛",
                        [
                            ("GF_R1_M1", "总决赛", ("winner", "UB_R2_M1"), ("winner", "LB_R2_M1")),
                        ],
                    ),
                ],
            ),
        ],
    },
    "8de": {
        "name": "8 队双败淘汰",
        "type": "double_elim",
        "total_teams": 8,
        "sections": [
            (
                "胜者组",
                [
                    (
                        "UB 第一轮",
                        [
                            ("UB_R1_M1", "胜者组第一轮 1", ("seed", 1), ("seed", 8)),
                            ("UB_R1_M2", "胜者组第一轮 2", ("seed", 4), ("seed", 5)),
                            ("UB_R1_M3", "胜者组第一轮 3", ("seed", 2), ("seed", 7)),
                            ("UB_R1_M4", "胜者组第一轮 4", ("seed", 3), ("seed", 6)),
                        ],
                    ),
                    (
                        "UB 第二轮",
                        [
                            (
                                "UB_R2_M1",
                                "胜者组第二轮 1",
                                ("winner", "UB_R1_M1"),
                                ("winner", "UB_R1_M2"),
                            ),
                            (
                                "UB_R2_M2",
                                "胜者组第二轮 2",
                                ("winner", "UB_R1_M3"),
                                ("winner", "UB_R1_M4"),
                            ),
                        ],
                    ),
                    (
                        "UB 决赛",
                        [
                            (
                                "UB_F_M1",
                                "胜者组决赛",
                                ("winner", "UB_R2_M1"),
                                ("winner", "UB_R2_M2"),
                            ),
                        ],
                    ),
                ],
            ),
            (
                "败者组",
                [
                    (
                        "LB 第一轮",
                        [
                            (
                                "LB_R1_M1",
                                "败者组第一轮 1",
                                ("loser", "UB_R1_M1"),
                                ("loser", "UB_R1_M2"),
                            ),
                            (
                                "LB_R1_M2",
                                "败者组第一轮 2",
                                ("loser", "UB_R1_M3"),
                                ("loser", "UB_R1_M4"),
                            ),
                        ],
                    ),
                    (
                        "LB 第二轮",
                        [
                            (
                                "LB_R2_M1",
                                "败者组第二轮 1",
                                ("winner", "LB_R1_M1"),
                                ("loser", "UB_R2_M2"),
                            ),
                            (
                                "LB_R2_M2",
                                "败者组第二轮 2",
                                ("winner", "LB_R1_M2"),
                                ("loser", "UB_R2_M1"),
                            ),
                        ],
                    ),
                    (
                        "LB 第三轮",
                        [
                            (
                                "LB_R3_M1",
                                "败者组第三轮",
                                ("winner", "LB_R2_M1"),
                                ("winner", "LB_R2_M2"),
                            ),
                        ],
                    ),
                    (
                        "LB 决赛",
                        [
                            ("LB_F_M1", "败者组决赛", ("winner", "LB_R3_M1"), ("loser", "UB_F_M1")),
                        ],
                    ),
                ],
            ),
            (
                "总决赛",
                [
                    (
                        "总决赛",
                        [
                            ("GF_R1_M1", "总决赛", ("winner", "UB_F_M1"), ("winner", "LB_F_M1")),
                        ],
                    ),
                ],
            ),
        ],
    },
}
