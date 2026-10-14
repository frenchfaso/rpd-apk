#include <QApplication>
#include <QStyle>
#include <QComboBox>
#include <QDial>
#include <QImage>
#include <QPainter>
#include <QStyleOption>
#include <fstream>
#include <iostream>
#include <string>

static bool check_rendering(QApplication &app, QStyle::ComplexControl control,
                            QStyleOptionComplex &option, QWidget &widget)
{
    const QRect rect = option.rect;
    auto render = [&]() {
        QImage image(240, 180, QImage::Format_ARGB32_Premultiplied);
        image.fill(Qt::transparent);
        QPainter painter(&image);
        app.style()->drawComplexControl(control, &option, &painter, &widget);
        return image;
    };
    const QImage first = render();
    const QImage cached = render();
    if (option.rect != rect || first != cached) {
        std::cerr << "Qt6 GTK2 cached rendering changed pixels or coordinates\n";
        return false;
    }
    bool painted = false;
    for (int y = 0; y < first.height(); ++y) {
        for (int x = 0; x < first.width(); ++x) {
            if (!qAlpha(first.pixel(x, y)))
                continue;
            painted = true;
            if (!rect.adjusted(-4, -4, 4, 4).contains(x, y)) {
                std::cerr << "Qt6 GTK2 control " << control << " painted outside its position at "
                          << x << ',' << y << '\n';
                return false;
            }
        }
    }
    if (!painted)
        std::cerr << "Qt6 GTK2 control painted no pixels\n";
    return painted;
}

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    if (app.style()->objectName() != QStringLiteral("qt6gtk2")) {
        std::cerr << "Qt6 did not select the GTK2 style: "
                  << app.style()->objectName().toStdString() << '\n';
        return 1;
    }
    bool platform_theme = false;
    bool style = false;
    std::ifstream maps("/proc/self/maps");
    std::string line;
    while (std::getline(maps, line)) {
        platform_theme |= line.find("/platformthemes/libqt6gtk2.so") != std::string::npos;
        style |= line.find("/styles/libqt6gtk2-style.so") != std::string::npos;
    }
    if (!platform_theme || !style) {
        std::cerr << "Qt6 GTK2 platform-theme/style plugins are not both loaded\n";
        return 1;
    }
    QDial dial;
    QStyleOptionSlider slider;
    slider.initFrom(&dial);
    slider.rect = QRect(40, 30, 120, 100);
    slider.state |= QStyle::State_Enabled;
    slider.minimum = 0;
    slider.maximum = 100;
    slider.sliderPosition = slider.sliderValue = 50;
    slider.tickInterval = 10;
    slider.subControls = QStyle::SC_DialGroove | QStyle::SC_DialHandle | QStyle::SC_DialTickmarks;
    if (!check_rendering(app, QStyle::CC_Dial, slider, dial))
        return 1;
    QComboBox box;
    box.addItem(QStringLiteral("Raspberry Pi"));
    QStyleOptionComboBox combo;
    combo.initFrom(&box);
    combo.rect = QRect(40, 30, 140, 36);
    combo.state |= QStyle::State_Enabled;
    combo.currentText = box.currentText();
    combo.subControls = QStyle::SC_All;
    for (bool editable : {false, true}) {
        box.setEditable(editable);
        combo.editable = editable;
        if (!check_rendering(app, QStyle::CC_ComboBox, combo, box))
            return 1;
    }
    std::cout << "Qt6 GTK2 platform-theme/style loaded; dial and combo cache rendering passed\n";
    return 0;
}
