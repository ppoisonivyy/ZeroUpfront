# Color choices for a hospital insurance worklist

Use dark navy text on near-white surfaces, deep blue for actions and selections, and amber with a written reason when staff need to act. A staff review and an insurer decision each get their own label. A deposit amount appears only after the hospital records its decision.

## What people preferred

In a tablet reading experiment with 40 Thai and 60 UK participants, 67.5% of the Thai participants and 68.4% of the UK participants preferred black text on white, pale blue or buff. The experiment found no reading-time effect of the five combinations. The sample included younger and older readers. It did not include a specific cohort of insurance coordinators. [Chatrangsan and Petrie, 2019](https://www.scitepress.org/Papers/2019/77378/77378.pdf)

In a controlled electronics-website study with 30 participants per country in Canada, Germany and Japan, blue had the highest mean appeal of the gray, blue and yellow treatments. Blue beat yellow in each sample. The study did not compare blue with teal. A much larger international website-rating experiment also found substantial differences in preferred colorfulness and complexity across groups. Blue is a defensible first version for interactive elements. Our particular shade remains a design choice. [Cyr, Head and Larios](https://milenahead.ca/Articles/Colour%20Appeal%20in%20Website%20Design%20within%20and%20across%20Cultures-%20A%20Multi-Method%20Evaluation.pdf) · [Reinecke and Gajos](https://www.iis.seas.harvard.edu/papers/2014/reinecke14visual.shtml)

## Color roles

| Element | Foreground | Background |
| --- | --- | --- |
| Ordinary text | Ink `#173445` | White |
| Help and metadata | Slate `#506874` | White or pale neutral |
| Primary action | White | Deep blue `#185A89` |
| Selected source or staff-reviewed badge | Deep blue | Pale blue `#E7F1FA` |
| Unresolved evidence | Amber `#844A0E` | Cream `#FFF3DC` |
| Error | Brick `#8B3829` | Pale red `#FFF0EB` |
| Keyboard focus | Blue `#145C93` | White separator |
| Editable field border | Slate `#788A97` | White |

The NHS service manual assigns colors to consistent functional roles. WCAG 2.2 requires sufficient contrast, and status must be understandable without color. The palette regression checks cover these text and control pairs. Keyboard navigation, legible adjacent labels, and messages explaining the next action matter just as much. [NHS design system](https://service-manual.nhs.uk/design-system/styles/colour) · [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)

To test preference locally, give Thai and English-speaking coordinators the same worklist in blue and teal with the presentation order balanced. Ask them to find a missing discharge attachment, inspect the guarantee limit and identify who owes a response. Record correct answers, time and misread statuses before asking which scheme they would use for a shift. We have not run that staff preference study.
